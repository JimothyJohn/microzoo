#!/usr/bin/env python3
"""edof.py: fuse a multi-focal stack into one all-in-focus clip, and Z per body.

Input is what ``ecosim.py --planes N`` writes: N synchronised cameras focused
``--plane-spacing`` apart, listed with their focal heights in the sidecar. Two
products, both from the same per-plane focus measure (Laplacian energy of a
lightly smoothed frame, box-averaged):

- **Fusion by selection.** Each output pixel is copied from the plane that is
  sharpest there. Nothing is synthesised: every pixel was measured by a real
  camera. That is the honest baseline any learned EDOF has to beat, and the only
  kind that is safe for footage presented as what was seen.
- **Z per body.** Focus energy summed over a body's footprint, one number per
  plane, peak refined by a parabola through the best plane and its neighbours:
  the focal-sweep Z of CLAUDE.md, with N cameras instead of a Z ramp.

When the clip comes from ecosim (a truth CSV and the all-in-focus oracle next
to it), both are scored: object-region PSNR of the fused clip and of every
single plane against the oracle, and Z error per body against ``z_um``.

    python ecosim.py --out data/st.mp4 --na 0.25 --um-per-px 0.6 --planes 3 \\
        --plane-spacing 25 --cast paramecium=4,didinium=1,debris=20
    python edof.py data/st.json            # -> st_edof.mp4, st_depth.mp4, st_edof.json

Pure numpy + OpenCV, so it runs on the Pi; fusing three 1080p planes live is
a Mac Studio job.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

__all__ = ["focus_measure", "fuse", "peak_z", "score_frame"]

SMOOTH_SIGMA_PX = 1.0  # pre-smoothing before the Laplacian, so sensor noise is not "sharp"
OBJECT_DELTA = 12.0  # |oracle - background| above this is "object" for the region PSNR
EXCLUDE = frozenset({"debris"})  # bodies not scored for Z (debris is scored by PSNR anyway)


def focus_measure(gray: np.ndarray, window: int) -> np.ndarray:
    """Per-pixel focus energy: box-averaged squared Laplacian of a smoothed frame."""
    g = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), SMOOTH_SIGMA_PX)
    lap = cv2.Laplacian(g, cv2.CV_32F, ksize=3)
    return cv2.boxFilter(lap * lap, -1, (window, window), normalize=True)


def fuse(stack: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(fused frame, sharpest-plane index, focus measures) for a (planes, H, W) stack.

    The index map is median-filtered so selection follows bodies, not noise grains;
    background (no plane sharper than another) falls wherever the median puts it,
    which is harmless: every plane's background is the same dark."""
    if stack.ndim != 3 or stack.shape[0] < 2:
        raise ValueError(f"need a (planes >= 2, H, W) stack, got shape {stack.shape}")
    fm = np.stack([focus_measure(p, window) for p in stack])
    idx = np.argmax(fm, axis=0).astype(np.uint8)
    idx = cv2.medianBlur(idx, 5)
    fused = np.take_along_axis(stack, idx[None].astype(np.intp), axis=0)[0]
    return fused, idx, fm


def peak_z(energy: np.ndarray, focuses: list[float]) -> float:
    """Focal height of peak focus energy: best plane, refined by a parabola through
    it and its neighbours (clamped to half a step). Planes must be evenly spaced."""
    if len(energy) != len(focuses) or len(focuses) < 2:
        raise ValueError("one energy per plane, at least two planes")
    k = int(np.argmax(energy))
    step = focuses[1] - focuses[0]
    if 0 < k < len(energy) - 1:
        a, b, c = (float(v) for v in energy[k - 1 : k + 2])
        den = a - 2 * b + c
        if den < 0:
            return focuses[k] + float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) * step
    return focuses[k]


def _psnr(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float | None:
    if not mask.any():
        return None
    mse = float(np.mean((a[mask].astype(np.float64) - b[mask].astype(np.float64)) ** 2))
    return 99.0 if mse == 0 else 10 * math.log10(255.0**2 / mse)


def score_frame(
    planes: np.ndarray, fused: np.ndarray, oracle: np.ndarray
) -> tuple[list[float | None], float | None]:
    """Object-region PSNR of every plane and of the fused frame against the oracle.
    Object region: where the oracle departs from its own median background."""
    bg = float(np.median(oracle))
    mask = np.abs(oracle.astype(np.float32) - bg) > OBJECT_DELTA
    mask = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    return [_psnr(p, oracle, mask) for p in planes], _psnr(fused, oracle, mask)


def _load_truth(path: Path) -> dict[int, list[tuple[float, float, float, float, str]]]:
    """{frame: [(x, y, length_px, z_um, species)]}"""
    out: dict[int, list[tuple[float, float, float, float, str]]] = defaultdict(list)
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out[int(row["frame"])].append(
                (
                    float(row["x"]),
                    float(row["y"]),
                    float(row["length_px"]),
                    float(row["z_um"]),
                    row["species"],
                )
            )
    return out


def _body_energy(fm: np.ndarray, x: float, y: float, r: float) -> np.ndarray:
    """Focus energy per plane summed over a disc of radius ``r`` px at (x, y)."""
    _, h, w = fm.shape
    r = max(2, int(math.ceil(r)))
    x0, x1 = max(0, int(x) - r), min(w, int(x) + r + 1)
    y0, y1 = max(0, int(y) - r), min(h, int(y) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return np.zeros(fm.shape[0])
    yy, xx = np.ogrid[y0:y1, x0:x1]
    disc = (xx - x) ** 2 + (yy - y) ** 2 <= r * r
    return fm[:, y0:y1, x0:x1][:, disc].sum(axis=1)


def _z_stats(
    zt: np.ndarray, ze: np.ndarray, lo: float, hi: float, step: float, depth: float
) -> dict:
    err = np.abs(ze - zt)
    inside = (zt >= lo) & (zt <= hi)
    return {
        "samples": len(zt),
        "mae_um": round(float(err.mean()), 2),
        "median_err_um": round(float(np.median(err)), 2),
        "within_half_step": round(float((err <= step / 2).mean()), 3),
        "inside_span_frac": round(float(inside.mean()), 3),
        "mae_inside_span_um": round(float(err[inside].mean()), 2) if inside.any() else None,
        "mae_guess_middle_um": round(float(np.abs(zt - depth / 2).mean()), 2),
    }


def _depth_vis(idx: np.ndarray, fm: np.ndarray) -> np.ndarray:
    """Sharpest-plane map as colour, dimmed where nothing is sharp (background)."""
    n = fm.shape[0]
    lut = (idx.astype(np.float32) * (255.0 / max(1, n - 1))).astype(np.uint8)
    col = cv2.applyColorMap(lut, cv2.COLORMAP_VIRIDIS)
    peak = fm.max(axis=0)
    ref = float(np.percentile(peak, 99)) or 1.0
    alpha = np.clip(peak / ref, 0, 1)[..., None]
    return (col * alpha).astype(np.uint8)


def _open(path: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise OSError(f"cannot open {path}")
    return cap


def run(sidecar_path: Path, window: int, write_video: bool = True) -> dict:
    sc = json.loads(sidecar_path.read_text())
    planes = sc.get("planes")
    if not planes or len(planes) < 2:
        raise ValueError(f"{sidecar_path}: no multi-plane clip (render with ecosim --planes N>=2)")
    d = sidecar_path.parent
    focuses = [float(p["focus_um"]) for p in planes]
    steps = np.diff(focuses)
    if not np.allclose(steps, steps[0]) or steps[0] <= 0:
        raise ValueError(f"planes must be evenly spaced, floor first: {focuses}")
    caps = [_open(d / p["file"]) for p in planes]
    oracle_cap = _open(d / sc["aif"]) if sc.get("aif") and (d / sc["aif"]).exists() else None
    stem = sidecar_path.stem
    truth_path = d / f"{stem}_truth.csv"
    truth = _load_truth(truth_path) if truth_path.exists() else {}
    fps = float(sc.get("fps", 30.0))
    writers: list[cv2.VideoWriter] = []
    try:
        psnr_planes: list[list[float]] = [[] for _ in planes]
        psnr_fused: list[float] = []
        zerr: list[tuple[float, float, bool]] = []  # (true z, estimate, isolated)
        frame = 0
        while True:
            grabs = [c.read() for c in caps]
            if not all(ok for ok, _ in grabs):
                break
            stack = np.stack([img[..., 0] for _, img in grabs])
            fused, idx, fm = fuse(stack, window)
            if write_video:
                if not writers:
                    h, w = fused.shape
                    four = cv2.VideoWriter.fourcc(*"mp4v")
                    for name in (f"{stem}_edof.mp4", f"{stem}_depth.mp4"):
                        wr = cv2.VideoWriter(str(d / name), four, fps, (w, h))
                        if not wr.isOpened():
                            raise OSError(f"cannot open writer: {d / name}")
                        writers.append(wr)
                writers[0].write(cv2.cvtColor(fused, cv2.COLOR_GRAY2BGR))
                writers[1].write(_depth_vis(idx, fm))
            if oracle_cap is not None:
                ok, o = oracle_cap.read()
                if ok:
                    per, fu = score_frame(stack, fused, o[..., 0])
                    if fu is not None:
                        psnr_fused.append(fu)
                        for k, v in enumerate(per):
                            if v is not None:  # same mask as fused: never None here
                                psnr_planes[k].append(v)
            bodies = [b for b in truth.get(frame, []) if b[4] not in EXCLUDE]
            for i, (x, y, length, z, _sp) in enumerate(bodies):
                e = _body_energy(fm, x, y, 0.25 * length)
                if e.max() > 0:
                    alone = all(
                        math.hypot(x - ox, y - oy) > 0.5 * (length + ol)
                        for j, (ox, oy, ol, _, _) in enumerate(bodies)
                        if j != i
                    )
                    zerr.append((z, peak_z(e, focuses), alone))
            frame += 1
    finally:
        for c in caps:
            c.release()
        if oracle_cap is not None:
            oracle_cap.release()
        for wr in writers:
            wr.release()
    if frame == 0:
        raise ValueError("no frames read")
    report: dict = {
        "frames": frame,
        "planes": len(planes),
        "focuses_um": focuses,
        "spacing_um": float(steps[0]),
        "dof_um": sc.get("dof_um"),
        "objective": sc.get("objective"),
        "window_px": window,
    }
    if psnr_fused:
        report["psnr_object_db"] = {
            "fused": round(float(np.mean(psnr_fused)), 2),
            "planes": [round(float(np.mean(v)), 2) for v in psnr_planes],
        }
        report["psnr_object_db"]["gain_over_best_plane"] = round(
            report["psnr_object_db"]["fused"] - max(report["psnr_object_db"]["planes"]), 2
        )
    if zerr:
        depth = float(sc.get("depth_um") or 0.0)
        lo, hi = focuses[0] - steps[0] / 2, focuses[-1] + steps[0] / 2
        zt = np.array([t for t, _, _ in zerr])
        ze = np.array([e for _, e, _ in zerr])
        alone = np.array([a for _, _, a in zerr])
        report["z"] = _z_stats(zt, ze, lo, hi, steps[0], depth)
        # one footprint cannot split two stacked bodies; that is a job for tracks
        if alone.any():
            report["z"]["isolated"] = _z_stats(zt[alone], ze[alone], lo, hi, steps[0], depth)
    if write_video:
        report["outputs"] = [f"{stem}_edof.mp4", f"{stem}_depth.mp4"]
    (d / f"{stem}_edof.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sidecar", type=Path, help="<stem>.json from ecosim --planes N")
    p.add_argument("--window", type=int, default=9, help="focus-measure box, px (odd)")
    p.add_argument("--no-video", action="store_true", help="score only, skip the mp4s")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.window < 1 or a.window % 2 == 0:
        print("edof: --window must be a positive odd number", file=sys.stderr)
        return 2
    try:
        r = run(a.sidecar, a.window, write_video=not a.no_video)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"edof: {e}", file=sys.stderr)
        return 2
    line = f"{r['planes']} planes x {r['spacing_um']:g} µm, {r['frames']} frames"
    if "psnr_object_db" in r:
        ps = r["psnr_object_db"]
        line += f"; object PSNR fused {ps['fused']} dB vs planes {ps['planes']}"
    if "z" in r:
        z = r["z"].get("isolated", r["z"])
        which = "isolated bodies" if "isolated" in r["z"] else "all bodies"
        line += (
            f"; Z MAE ({which}) {z['mae_um']} µm, {z['mae_inside_span_um']} inside the "
            f"planes' span (guessing the middle: {z['mae_guess_middle_um']}); "
            f"{z['inside_span_frac']:.0%} inside the span"
        )
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
