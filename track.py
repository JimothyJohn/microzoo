#!/usr/bin/env python3
"""track.py: v1 multi-target tracker for darkfield pond footage.

Pipeline: MOG2 background subtraction -> morphology -> contours -> per-track
constant-velocity Kalman -> greedy nearest-neighbour assignment.

Two passes over the video. Pass 1 builds tracks (optionally on a downscaled
frame, --scale). Pass 2 re-reads the full-resolution video and writes:

    <stem>_tracks.mp4         boxes, IDs and trails for every confirmed track
    <stem>_tracks.csv         frame, t, track_id, x, y, area, w, h (full-res px)
    <stem>_follow_<id>.mp4    fixed-size crop riding the chosen track
    <stem>_tracks.json        parameters, video metadata, per-track summary,
                              plus <stem>.json (the clip sidecar) if present

Runtime deps: numpy, opencv (headless). No scipy, so the Pi can run it.
Known weakness: greedy assignment swaps IDs when two swimmers cross.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

__all__ = [
    "Detection",
    "Track",
    "Tracker",
    "detect",
    "greedy_assign",
    "run",
    "main",
]


@dataclass(frozen=True)
class Detection:
    """One blob in one frame. Coordinates are full-resolution pixels."""

    x: float
    y: float
    area: float
    w: int
    h: int


@dataclass
class Track:
    id: int
    first_frame: int
    last_frame: int
    kf: cv2.KalmanFilter = field(repr=False)
    missed: int = 0
    # (frame, x, y, area, w, h) for every frame with a measurement.
    points: list[tuple[int, float, float, float, int, int]] = field(default_factory=list)

    @property
    def hits(self) -> int:
        return len(self.points)

    @property
    def life(self) -> int:
        """Frames spanned, inclusive."""
        return self.last_frame - self.first_frame + 1

    def predicted_xy(self) -> tuple[float, float]:
        s = self.kf.statePre if self.missed else self.kf.statePost
        return float(s[0, 0]), float(s[1, 0])


def _make_kalman(x: float, y: float, process_noise: float, measurement_noise: float):
    kf = cv2.KalmanFilter(4, 2, 0, cv2.CV_32F)
    kf.transitionMatrix = np.array(
        [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float32
    )
    kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
    kf.processNoiseCov = np.eye(4, dtype=np.float32) * process_noise
    kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * measurement_noise
    kf.errorCovPost = np.eye(4, dtype=np.float32)
    kf.statePost = np.array([[x], [y], [0.0], [0.0]], dtype=np.float32)
    kf.statePre = kf.statePost.copy()
    return kf


def detect(
    mask: np.ndarray, min_area: float, max_area: float, inv_scale: float = 1.0
) -> list[Detection]:
    """Blobs in a binary foreground mask, mapped back to full-res coordinates.

    ``min_area``/``max_area`` are in full-res px^2. ``inv_scale`` is 1/scale of
    the mask relative to the full frame.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[Detection] = []
    area_scale = inv_scale * inv_scale
    for c in contours:
        area = float(cv2.contourArea(c)) * area_scale
        if area < min_area or area > max_area:
            continue
        m = cv2.moments(c)
        if m["m00"] <= 0:
            continue
        cx = m["m10"] / m["m00"] * inv_scale
        cy = m["m01"] / m["m00"] * inv_scale
        _, _, w, h = cv2.boundingRect(c)
        out.append(
            Detection(
                x=cx,
                y=cy,
                area=area,
                w=max(1, int(round(w * inv_scale))),
                h=max(1, int(round(h * inv_scale))),
            )
        )
    return out


def greedy_assign(preds: np.ndarray, dets: np.ndarray, max_dist: float) -> list[tuple[int, int]]:
    """Greedy nearest-neighbour matching.

    ``preds`` is (N, 2), ``dets`` is (M, 2). Returns (pred_index, det_index)
    pairs, each index used at most once, every pair closer than ``max_dist``.
    Pairs are taken in increasing distance order, which is what makes two
    crossing swimmers swap IDs. The fix is a global assignment (Hungarian);
    left out to keep scipy off the Pi.
    """
    preds = np.asarray(preds, dtype=np.float64).reshape(-1, 2)
    dets = np.asarray(dets, dtype=np.float64).reshape(-1, 2)
    if preds.shape[0] == 0 or dets.shape[0] == 0 or not max_dist > 0:
        return []
    d = np.linalg.norm(preds[:, None, :] - dets[None, :, :], axis=2)
    d = np.where(np.isfinite(d), d, np.inf)
    order = np.argsort(d, axis=None, kind="stable")
    used_p = np.zeros(preds.shape[0], dtype=bool)
    used_d = np.zeros(dets.shape[0], dtype=bool)
    pairs: list[tuple[int, int]] = []
    n_d = dets.shape[0]
    for flat in order:
        dist = d.flat[flat]
        if not dist < max_dist:
            break
        i, j = divmod(int(flat), n_d)
        if used_p[i] or used_d[j]:
            continue
        used_p[i] = used_d[j] = True
        pairs.append((i, j))
        if used_p.all() or used_d.all():
            break
    return pairs


class Tracker:
    """Owns the live tracks; call ``step`` once per frame in order."""

    def __init__(
        self,
        max_dist: float,
        max_missed: int,
        birth_dist: float | None = None,
        process_noise: float = 1e-2,
        measurement_noise: float = 1.0,
    ):
        self.max_dist = max_dist
        self.max_missed = max_missed
        # An unmatched detection closer than this to any live track's prediction
        # is a fragment of that track's blob (MOG2 splits slow swimmers), not a
        # new organism. Without this the fragment spawns a track that out-competes
        # and kills the established one on the next frame.
        self.birth_dist = max_dist / 2 if birth_dist is None else birth_dist
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self.live: list[Track] = []
        self.dead: list[Track] = []
        self._next_id = 1

    def step(self, frame_idx: int, dets: list[Detection]) -> None:
        for t in self.live:
            t.kf.predict()
        preds = np.array([t.predicted_xy() for t in self.live], dtype=np.float64).reshape(-1, 2)
        pts = np.array([(d.x, d.y) for d in dets], dtype=np.float64).reshape(-1, 2)
        pairs = greedy_assign(preds, pts, self.max_dist)

        matched_t = set()
        matched_d = set()
        for i, j in pairs:
            t, d = self.live[i], dets[j]
            t.kf.correct(np.array([[d.x], [d.y]], dtype=np.float32))
            t.missed = 0
            t.last_frame = frame_idx
            t.points.append((frame_idx, d.x, d.y, d.area, d.w, d.h))
            matched_t.add(i)
            matched_d.add(j)

        still_live: list[Track] = []
        for i, t in enumerate(self.live):
            if i in matched_t:
                still_live.append(t)
                continue
            t.missed += 1
            if t.missed > self.max_missed:
                self.dead.append(t)
            else:
                still_live.append(t)
        self.live = still_live

        for j, d in enumerate(dets):
            if j in matched_d:
                continue
            if preds.shape[0] and self.birth_dist > 0:
                near = np.linalg.norm(preds - pts[j], axis=1).min()
                if near < self.birth_dist:
                    continue
            kf = _make_kalman(d.x, d.y, self.process_noise, self.measurement_noise)
            t = Track(id=self._next_id, first_frame=frame_idx, last_frame=frame_idx, kf=kf)
            t.points.append((frame_idx, d.x, d.y, d.area, d.w, d.h))
            self._next_id += 1
            self.live.append(t)

    def all_tracks(self) -> list[Track]:
        return sorted(self.dead + self.live, key=lambda t: t.id)


# ----------------------------------------------------------------------------
# Video I/O helpers


class VideoError(RuntimeError):
    pass


def _open(path: Path) -> tuple[cv2.VideoCapture, int, int, float, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise VideoError(f"cannot open video: {path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if w <= 0 or h <= 0:
        cap.release()
        raise VideoError(f"video reports no frame size: {path}")
    return cap, w, h, fps, n


def _writer(path: Path, fps: float, size: tuple[int, int]) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter.fourcc(*"mp4v")
    wr = cv2.VideoWriter(str(path), fourcc, fps if fps > 0 else 30.0, size)
    if not wr.isOpened():
        raise VideoError(f"cannot open writer: {path}")
    return wr


def _color(track_id: int, bright_background: bool = False) -> tuple[int, int, int]:
    """Stable per-id hue. Full value on a dark field; darker on a bright one so the
    overlay stays legible on backlit (brightfield) footage."""
    rng = np.random.default_rng(track_id)
    value = 150 if bright_background else 255
    hsv = np.array([[[int(rng.integers(0, 180)), 220, value]]], dtype=np.uint8)
    b, g, r = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


def _follow_path(track: Track, alpha: float) -> dict[int, tuple[float, float]]:
    """Per-frame crop centre for a track: linear interpolation across missed
    frames, then an exponential moving average so the window doesn't jitter."""
    frames = np.array([p[0] for p in track.points])
    xs = np.array([p[1] for p in track.points])
    ys = np.array([p[2] for p in track.points])
    all_frames = np.arange(track.first_frame, track.last_frame + 1)
    xi = np.interp(all_frames, frames, xs)
    yi = np.interp(all_frames, frames, ys)
    out: dict[int, tuple[float, float]] = {}
    sx, sy = xi[0], yi[0]
    for f, x, y in zip(all_frames, xi, yi, strict=True):
        sx += alpha * (x - sx)
        sy += alpha * (y - sy)
        out[int(f)] = (float(sx), float(sy))
    return out


def _crop(frame: np.ndarray, cx: float, cy: float, size: int) -> np.ndarray:
    h, w = frame.shape[:2]
    half = size // 2
    x0 = int(round(cx)) - half
    y0 = int(round(cy)) - half
    x0 = min(max(x0, 0), max(w - size, 0))
    y0 = min(max(y0, 0), max(h - size, 0))
    crop = frame[y0 : y0 + size, x0 : x0 + size]
    if crop.shape[0] != size or crop.shape[1] != size:
        # Frame smaller than the window: pad with black.
        pad = np.zeros((size, size, 3), dtype=frame.dtype)
        pad[: crop.shape[0], : crop.shape[1]] = crop
        crop = pad
    return crop


# ----------------------------------------------------------------------------
# Main pipeline


def _pass1(args: argparse.Namespace, path: Path) -> tuple[Tracker, dict]:
    cap, w, h, fps, n_reported = _open(path)
    scale = args.scale
    inv = 1.0 / scale
    frame_area = w * h
    max_area = args.max_area if args.max_area is not None else 0.05 * frame_area
    mog = cv2.createBackgroundSubtractorMOG2(
        history=args.history, varThreshold=args.thresh, detectShadows=False
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    tracker = Tracker(
        max_dist=args.max_dist, max_missed=args.max_missed, birth_dist=args.birth_dist
    )

    idx = 0
    t0 = time.monotonic()
    median_gray = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = frame if scale == 1.0 else cv2.resize(frame, None, fx=scale, fy=scale)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if idx == 0:
            # Polarity of the illumination. MOG2 does not care (foreground is any
            # deviation from the background model); the overlay colours do.
            median_gray = float(np.median(gray))
        fg = mog.apply(gray)
        if idx >= args.warmup:
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
            fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
            dets = detect(fg, args.min_area, max_area, inv)
        else:
            dets = []
        tracker.step(idx, dets)
        idx += 1
    cap.release()
    if idx == 0:
        raise VideoError(f"video has no decodable frames: {path}")
    meta = {
        "width": w,
        "height": h,
        "fps": fps,
        "frames": idx,
        "frames_reported": n_reported,
        "median_gray": median_gray,
        "background": "bright" if median_gray > 127 else "dark",
        "pass1_seconds": round(time.monotonic() - t0, 3),
        "max_area": max_area,
    }
    return tracker, meta


def _pass2(
    args: argparse.Namespace,
    path: Path,
    stem: Path,
    tracks: list[Track],
    follow: Track | None,
    meta: dict,
) -> dict[str, str]:
    """Render overlay video and follow clip. Returns {kind: filename}."""
    outputs: dict[str, str] = {}
    cap, w, h, fps, _ = _open(path)
    by_frame: dict[int, list[Track]] = {}
    for t in tracks:
        for f in range(t.first_frame, t.last_frame + 1):
            by_frame.setdefault(f, []).append(t)
    # Per-track measured points indexed by frame, for boxes and trails.
    pts_by_track = {t.id: {p[0]: p for p in t.points} for t in tracks}

    overlay = None
    if not args.no_video:
        overlay_path = stem.with_name(stem.name + "_tracks.mp4")
        overlay = _writer(overlay_path, fps, (w, h))
        outputs["tracks_video"] = overlay_path.name

    follow_wr = None
    follow_path: dict[int, tuple[float, float]] = {}
    if follow is not None:
        follow_path = _follow_path(follow, args.follow_smooth)
        follow_out = stem.with_name(f"{stem.name}_follow_{follow.id}.mp4")
        follow_wr = _writer(follow_out, fps, (args.follow_size, args.follow_size))
        outputs["follow_video"] = follow_out.name

    trail = args.trail
    bright = meta.get("background") == "bright"
    hud = (0, 0, 0) if bright else (255, 255, 255)
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if follow_wr is not None and idx in follow_path:
            cx, cy = follow_path[idx]
            follow_wr.write(_crop(frame, cx, cy, args.follow_size))
        if overlay is not None:
            for t in by_frame.get(idx, ()):
                col = _color(t.id, bright)
                pts = pts_by_track[t.id]
                hist = [pts[f] for f in range(max(t.first_frame, idx - trail), idx + 1) if f in pts]
                for a, b in zip(hist, hist[1:], strict=False):
                    cv2.line(
                        frame,
                        (int(a[1]), int(a[2])),
                        (int(b[1]), int(b[2])),
                        col,
                        1,
                        cv2.LINE_AA,
                    )
                p = pts.get(idx)
                if p is not None:
                    _, x, y, _, bw, bh = p
                    x0, y0 = int(x - bw / 2), int(y - bh / 2)
                    cv2.rectangle(frame, (x0, y0), (x0 + bw, y0 + bh), col, 1)
                    cv2.putText(
                        frame,
                        str(t.id),
                        (x0, max(y0 - 3, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        col,
                        1,
                        cv2.LINE_AA,
                    )
            cv2.putText(
                frame,
                f"f{idx} tracks={len(by_frame.get(idx, ()))}",
                (6, 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                hud,
                1,
                cv2.LINE_AA,
            )
            overlay.write(frame)
        idx += 1
    cap.release()
    if overlay is not None:
        overlay.release()
    if follow_wr is not None:
        follow_wr.release()
    return outputs


def _write_csv(path: Path, tracks: list[Track], fps: float) -> int:
    rows = 0
    with path.open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["frame", "t", "track_id", "x", "y", "area", "w", "h"])
        for t in tracks:
            for f, x, y, area, w, h in t.points:
                ts = f / fps if fps > 0 else ""
                wr.writerow(
                    [
                        f,
                        f"{ts:.4f}" if ts != "" else "",
                        t.id,
                        f"{x:.2f}",
                        f"{y:.2f}",
                        f"{area:.1f}",
                        w,
                        h,
                    ]
                )
                rows += 1
    return rows


def _track_summary(t: Track, fps: float) -> dict:
    xy = np.array([(p[1], p[2]) for p in t.points])
    step = np.linalg.norm(np.diff(xy, axis=0), axis=1) if len(xy) > 1 else np.zeros(0)
    frames_between = np.diff([p[0] for p in t.points]) if len(xy) > 1 else np.ones(0)
    speed = step / np.maximum(frames_between, 1) if len(step) else np.zeros(0)
    return {
        "id": t.id,
        "first_frame": t.first_frame,
        "last_frame": t.last_frame,
        "life_frames": t.life,
        "hits": t.hits,
        "duration_s": round(t.life / fps, 3) if fps > 0 else None,
        "mean_speed_px_per_frame": round(float(speed.mean()), 3) if len(speed) else 0.0,
        "mean_area": round(float(np.mean([p[3] for p in t.points])), 1),
    }


def _load_sidecar(stem: Path) -> tuple[dict | None, str | None]:
    sc = stem.with_suffix(".json")
    if not sc.exists():
        return None, None
    try:
        with sc.open() as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return None, f"sidecar {sc.name} unreadable: {e}"
    if not isinstance(data, dict):
        return None, f"sidecar {sc.name} is not a JSON object"
    return data, None


def run(args: argparse.Namespace) -> int:
    path = Path(args.video)
    if not path.is_file():
        print(f"track: no such file: {path}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / path.stem

    try:
        tracker, meta = _pass1(args, path)
    except VideoError as e:
        print(f"track: {e}", file=sys.stderr)
        return 2

    confirmed = [t for t in tracker.all_tracks() if t.life >= args.min_life and t.hits >= 2]
    fps = meta["fps"]

    follow: Track | None = None
    warnings: list[str] = []
    if confirmed:
        if args.follow is None:
            follow = max(confirmed, key=lambda t: (t.hits, -t.id))
        else:
            follow = next((t for t in confirmed if t.id == args.follow), None)
            if follow is None:
                warnings.append(f"--follow {args.follow}: no confirmed track with that id")
    elif args.follow is not None:
        warnings.append("no confirmed tracks; nothing to follow")

    csv_path = stem.with_name(stem.name + "_tracks.csv")
    rows = _write_csv(csv_path, confirmed, fps)
    outputs = {"csv": csv_path.name}

    try:
        outputs.update(_pass2(args, path, stem, confirmed, follow, meta))
    except VideoError as e:
        print(f"track: {e}", file=sys.stderr)
        return 2

    sidecar, sc_warn = _load_sidecar(path.parent / path.stem)
    if sc_warn:
        warnings.append(sc_warn)

    summary = {
        "video": path.name,
        "params": {k: v for k, v in vars(args).items() if k not in {"video", "out_dir"}},
        "meta": meta,
        "n_tracks_total": len(tracker.all_tracks()),
        "n_tracks_confirmed": len(confirmed),
        "csv_rows": rows,
        "follow_id": follow.id if follow else None,
        "outputs": outputs,
        "tracks": [_track_summary(t, fps) for t in confirmed],
        "warnings": warnings,
        "sidecar": sidecar,
    }
    json_path = stem.with_name(stem.name + "_tracks.json")
    with json_path.open("w") as fh:
        json.dump(summary, fh, indent=2)

    for wmsg in warnings:
        print(f"track: warning: {wmsg}", file=sys.stderr)
    print(
        f"{path.name}: {meta['frames']} frames, {len(confirmed)} confirmed tracks "
        f"({len(tracker.all_tracks())} total), {rows} rows -> {csv_path.name}"
        + (f", follow id {follow.id}" if follow else ""),
    )
    return 0


def _positive_fraction(s: str) -> float:
    v = float(s)
    if not 0 < v <= 1:
        raise argparse.ArgumentTypeError("must be in (0, 1]")
    return v


def _positive_int(s: str) -> int:
    v = int(s)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def _nonneg_int(s: str) -> int:
    v = int(s)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


def _even_int(s: str) -> int:
    v = int(s)
    if v < 16 or v % 2:
        raise argparse.ArgumentTypeError("must be an even integer >= 16")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("video", help="input clip (anything OpenCV can decode)")
    p.add_argument("--out-dir", help="write outputs here instead of next to the input")
    p.add_argument(
        "--min-area",
        type=float,
        default=30.0,
        help="min blob area, full-res px^2 (the knob you'll actually turn)",
    )
    p.add_argument(
        "--max-area",
        type=float,
        default=None,
        help="max blob area, full-res px^2 (default 5%% of frame)",
    )
    p.add_argument("--thresh", type=float, default=16.0, help="MOG2 varThreshold")
    p.add_argument("--history", type=_positive_int, default=500, help="MOG2 history frames")
    p.add_argument(
        "--max-dist", type=float, default=40.0, help="max assignment distance, full-res px"
    )
    p.add_argument(
        "--birth-dist",
        type=float,
        default=None,
        help="unmatched blobs closer than this to a live track are fragments, not new tracks "
        "(default: half of --max-dist; 0 disables)",
    )
    p.add_argument(
        "--max-missed",
        type=_nonneg_int,
        default=10,
        help="frames a track survives without a detection",
    )
    p.add_argument(
        "--min-life", type=_positive_int, default=15, help="min frames spanned for a track to count"
    )
    p.add_argument(
        "--scale",
        type=_positive_fraction,
        default=1.0,
        help="detect on a downscaled frame (0.5 on the Pi at 1080p); outputs stay full-res",
    )
    p.add_argument(
        "--warmup", type=_nonneg_int, default=2, help="frames to let MOG2 settle before detecting"
    )
    p.add_argument(
        "--follow", type=int, default=None, help="track id for the follow clip (default: most hits)"
    )
    p.add_argument("--follow-size", type=_even_int, default=256, help="follow crop size, px")
    p.add_argument(
        "--follow-smooth",
        type=_positive_fraction,
        default=0.2,
        help="EMA factor for the follow window (1 = no smoothing)",
    )
    p.add_argument(
        "--trail", type=_nonneg_int, default=30, help="trail length in frames on the overlay"
    )
    p.add_argument(
        "--no-video",
        action="store_true",
        help="skip the overlay video (CSV, JSON and follow clip still written)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
