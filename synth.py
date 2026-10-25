#!/usr/bin/env python3
"""synth.py: synthetic darkfield swimmers for testing track.py without a culture.

Bright ellipses on a dark, noisy background. Each swimmer keeps a heading that
random-walks, moves at a roughly constant speed and reflects off the frame
edges. Deterministic for a given seed.

    python synth.py --out data/demo.mp4 --n 6 --frames 300 --seed 1

Writes <out> and <out stem>_truth.csv (frame, obj_id, x, y) so tests can score
the tracker against ground truth. ``--mode cross`` instead launches two
swimmers on straight lines through the frame centre, which is the case greedy
assignment gets wrong.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np


def simulate(
    n: int,
    frames: int,
    size: tuple[int, int],
    speed: float,
    seed: int,
    turn_sigma: float = 0.25,
    margin: float = 12.0,
) -> np.ndarray:
    """Positions of ``n`` swimmers over ``frames`` frames, shape (frames, n, 2).

    Swimmers start spread apart (no two closer than 4*margin) and reflect off
    the walls, so every one stays visible for the whole clip.
    """
    w, h = size
    rng = np.random.default_rng(seed)
    pos = np.zeros((frames, n, 2))
    starts: list[np.ndarray] = []
    for _ in range(n):
        for _attempt in range(1000):
            cand = rng.uniform([margin, margin], [w - margin, h - margin])
            if all(np.linalg.norm(cand - s) >= 4 * margin for s in starts):
                break
        starts.append(cand)
    p = np.array(starts, dtype=np.float64).reshape(n, 2)
    heading = rng.uniform(0, 2 * np.pi, n)
    spd = speed * rng.uniform(0.7, 1.3, n)
    for f in range(frames):
        pos[f] = p
        heading += rng.normal(0, turn_sigma, n)
        step = np.stack([np.cos(heading), np.sin(heading)], axis=1) * spd[:, None]
        p = p + step
        for k in range(n):
            if p[k, 0] < margin or p[k, 0] > w - margin:
                heading[k] = np.pi - heading[k]
                p[k, 0] = np.clip(p[k, 0], margin, w - margin)
            if p[k, 1] < margin or p[k, 1] > h - margin:
                heading[k] = -heading[k]
                p[k, 1] = np.clip(p[k, 1], margin, h - margin)
    return pos


def simulate_cross(frames: int, size: tuple[int, int], speed: float) -> np.ndarray:
    """Two swimmers on straight lines that cross at the frame centre mid-clip."""
    w, h = size
    cx, cy = w / 2, h / 2
    half = frames / 2
    t = np.arange(frames) - half
    a = np.stack([cx + speed * t, cy + speed * t * 0.6], axis=1)
    b = np.stack([cx - speed * t, cy + speed * t * 0.6], axis=1)
    pos = np.stack([a, b], axis=1)
    pos[..., 0] = np.clip(pos[..., 0], 4, w - 4)
    pos[..., 1] = np.clip(pos[..., 1], 4, h - 4)
    return pos


POLARITIES = ("darkfield", "brightfield")


def render_frame(
    pos: np.ndarray,
    size: tuple[int, int],
    radius: float,
    rng: np.random.Generator,
    noise: float = 6.0,
    aspect: float = 0.55,
    headings: np.ndarray | None = None,
    polarity: str = "darkfield",
) -> np.ndarray:
    """One BGR frame with swimmers at ``pos`` (n, 2).

    ``darkfield``: bright bodies (200) on a dark field (18), the glow of a protist
    against a darkfield stop. ``brightfield``: dark bodies (95) with a lighter
    translucent centre (165) on a bright field (225), which is what a backlit
    TOMLOV or a condenser without a stop produces.
    """
    if polarity not in POLARITIES:
        raise ValueError(f"polarity must be one of {POLARITIES}, got {polarity!r}")
    w, h = size
    bright = polarity == "brightfield"
    background, body, core = (225, 95, 165) if bright else (18, 200, 200)
    img = np.full((h, w), background, dtype=np.float32)
    img += rng.normal(0, noise, img.shape).astype(np.float32)
    canvas = np.full((h, w), 255 if bright else 0, dtype=np.uint8)
    for k, (x, y) in enumerate(pos):
        ang = float(np.degrees(headings[k])) if headings is not None else 0.0
        centre = (int(round(x)), int(round(y)))
        a, b = int(round(radius)), max(1, int(round(radius * aspect)))
        cv2.ellipse(canvas, centre, (a, b), ang, 0, 360, body, -1, cv2.LINE_AA)
        if core != body:
            cv2.ellipse(
                canvas, centre, (max(1, a // 2), max(1, b // 2)), ang, 0, 360, core, -1, cv2.LINE_AA
            )
    canvas_f = cv2.GaussianBlur(canvas.astype(np.float32), (0, 0), 0.8)
    img = np.minimum(img, canvas_f) if bright else np.maximum(img, canvas_f)
    gray = np.clip(img, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def write_clip(
    out: Path,
    pos: np.ndarray,
    size: tuple[int, int],
    fps: float,
    radius: float,
    seed: int,
    noise: float = 6.0,
    polarity: str = "darkfield",
) -> Path:
    """Encode ``pos`` (frames, n, 2) to ``out`` and write ``<stem>_truth.csv``."""
    w, h = size
    out.parent.mkdir(parents=True, exist_ok=True)
    wr = cv2.VideoWriter(str(out), cv2.VideoWriter.fourcc(*"mp4v"), fps, (w, h))
    if not wr.isOpened():
        raise RuntimeError(f"cannot open writer: {out}")
    rng = np.random.default_rng(seed + 1_000_003)
    frames, n, _ = pos.shape
    headings = np.zeros(n)
    for f in range(frames):
        if f + 1 < frames:
            d = pos[f + 1] - pos[f]
            headings = np.arctan2(d[:, 1], d[:, 0])
        wr.write(
            render_frame(
                pos[f], size, radius, rng, noise=noise, headings=headings, polarity=polarity
            )
        )
    wr.release()
    truth = out.with_name(out.stem + "_truth.csv")
    with truth.open("w", newline="") as fh:
        cw = csv.writer(fh)
        cw.writerow(["frame", "obj_id", "x", "y"])
        for f in range(frames):
            for k in range(n):
                cw.writerow([f, k, f"{pos[f, k, 0]:.3f}", f"{pos[f, k, 1]:.3f}"])
    return truth


def _size(s: str) -> tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        w, h = int(w), int(h)
    except ValueError as e:
        raise argparse.ArgumentTypeError("expected WxH, e.g. 640x480") from e
    if w < 32 or h < 32:
        raise argparse.ArgumentTypeError("size must be at least 32x32")
    return w, h


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", type=Path, required=True, help="output .mp4")
    p.add_argument("--mode", choices=["walk", "cross", "static"], default="walk")
    p.add_argument("--n", type=int, default=5, help="swimmers (walk mode)")
    p.add_argument("--frames", type=int, default=240)
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--size", type=_size, default=(640, 480))
    p.add_argument("--speed", type=float, default=3.0, help="px per frame")
    p.add_argument("--radius", type=float, default=6.0, help="swimmer semi-major axis, px")
    p.add_argument("--noise", type=float, default=6.0, help="background noise sigma")
    p.add_argument(
        "--polarity",
        choices=POLARITIES,
        default="darkfield",
        help="darkfield: bright swimmers on black; brightfield: dark swimmers on white (backlit)",
    )
    p.add_argument("--seed", type=int, default=0)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.frames < 1 or a.n < 0:
        print("synth: frames must be >= 1 and n >= 0", file=sys.stderr)
        return 2
    if a.mode == "cross":
        pos = simulate_cross(a.frames, a.size, a.speed)
    elif a.mode == "static":
        pos = np.repeat(simulate(a.n, 1, a.size, 0.0, a.seed), a.frames, axis=0)
    else:
        pos = simulate(a.n, a.frames, a.size, a.speed, a.seed)
    truth = write_clip(
        a.out, pos, a.size, a.fps, a.radius, a.seed, noise=a.noise, polarity=a.polarity
    )
    print(f"{a.out} ({pos.shape[0]} frames, {pos.shape[1]} swimmers) + {truth.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
