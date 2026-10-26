#!/usr/bin/env python3
"""trackstats.py: turn a track CSV back into the numbers species.py is made of.

This is the return leg of the loop. ecosim.py turns parameters (speed, turn
rate, ...) into footage; track.py turns footage into ``<stem>_tracks.csv``;
this script turns that CSV into per-track motion statistics in real units,
and, when the clip has a ``_truth.csv`` with species labels (every ecosim clip
does), into a per-species estimate in exactly the shape ``ecosim.py --params``
accepts. Run it on real footage once G4 labels exist and the sim starts
learning from the pond instead of from a cheat sheet.

    python trackstats.py data/eco_tracks.csv            # scale/fps from data/eco.json
    python trackstats.py data/clip_tracks.csv --um-per-px 1.5 --fps 60
    python trackstats.py data/eco_tracks.csv --emit-params fitted.json

Convection is removed first: the per-frame median velocity of every track
present in two consecutive frames is taken as the current (the v3 rule from
CLAUDE.md) and subtracted before anything is called swimming.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

__all__ = [
    "common_motion",
    "load_tracks",
    "load_truth",
    "match_species",
    "per_species",
    "track_stats",
]

STATIONARY_UM_S = 20.0  # below this a step is "not swimming"


def load_tracks(path: Path) -> dict[int, np.ndarray]:
    """{track_id: array (n, 4) of frame, x, y, area} sorted by frame."""
    rows: dict[int, list[tuple[int, float, float, float]]] = defaultdict(list)
    with path.open(newline="") as fh:
        r = csv.DictReader(fh)
        need = {"frame", "track_id", "x", "y"}
        if r.fieldnames is None or not need <= set(r.fieldnames):
            raise ValueError(f"{path}: expected columns {sorted(need)}, got {r.fieldnames}")
        for row in r:
            rows[int(row["track_id"])].append(
                (int(row["frame"]), float(row["x"]), float(row["y"]), float(row.get("area") or 0))
            )
    return {tid: np.array(sorted(v), dtype=np.float64) for tid, v in rows.items()}


def load_truth(path: Path) -> dict[int, dict[int, tuple[float, float, str]]]:
    """{frame: {obj_id: (x, y, species)}} from an ecosim/synth truth CSV."""
    out: dict[int, dict[int, tuple[float, float, str]]] = defaultdict(dict)
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out[int(row["frame"])][int(row["obj_id"])] = (
                float(row["x"]),
                float(row["y"]),
                row.get("species") or "unknown",
            )
    return out


def _windowed(t: np.ndarray, win: int) -> tuple[np.ndarray, np.ndarray]:
    """(end frames, displacement px per frame) over every ``win``-frame span of a
    track that has no gap, i.e. frames f-win and f both present with exactly
    win frames between them."""
    f = t[:, 0].astype(int)
    idx = {int(fr): i for i, fr in enumerate(f)}
    ends, vel = [], []
    for i, fr in enumerate(f):
        j = idx.get(int(fr) - win)
        if j is not None and i - j == win:
            ends.append(int(fr))
            vel.append((t[i, 1:3] - t[j, 1:3]) / win)
    if not ends:
        return np.zeros(0, int), np.zeros((0, 2))
    return np.array(ends), np.array(vel)


def common_motion(tracks: dict[int, np.ndarray], n_frames: int, win: int = 1) -> np.ndarray:
    """Convection estimate: per-frame velocity (px/frame) that most tracks share.

    For every frame, the velocities of all tracks over the ``win`` frames ending
    there are pooled and the median taken. The median only counts when it is a
    consensus: at least three tracks, and at least a third of them, within a
    tight band around it (a fifth of its size, or a sub-pixel floor). Six
    swimmers heading six ways have no consensus and get 0;
    thirty debris specks riding one current do. Frames without a consensus
    are 0.
    """
    pool: dict[int, list[np.ndarray]] = defaultdict(list)
    for t in tracks.values():
        ends, vel = _windowed(t, win)
        for fr, v in zip(ends, vel, strict=True):
            pool[fr].append(v)
    out = np.zeros((n_frames, 2))
    for fr, vs in pool.items():
        if not (0 <= fr < n_frames) or len(vs) < 3:
            continue
        v = np.array(vs)
        med = np.median(v, axis=0)
        dev = np.linalg.norm(v - med, axis=1)
        tol = max(0.15, 0.2 * float(np.linalg.norm(med)))
        inside = int((dev <= tol).sum())
        if inside >= max(3, len(v) / 3):
            out[fr] = np.median(v[dev <= tol], axis=0)
    return out


def track_stats(
    t: np.ndarray, drift_px: np.ndarray, um_per_px: float, fps: float, win: int = 1
) -> dict[str, float]:
    """Motion statistics of one track in µm and seconds, convection removed.
    Speeds and headings come from displacement over ``win`` frames, which keeps
    centroid jitter from reading as motion."""
    f = t[:, 0].astype(int)
    xy = t[:, 1:3] * um_per_px
    ends, vel = _windowed(t, win)
    dt = 1.0 / fps
    if len(ends):
        vel = (vel - drift_px[np.clip(ends, 0, len(drift_px) - 1)]) * um_per_px / dt  # µm/s
    speed = np.linalg.norm(vel, axis=1) if len(vel) else np.zeros(0)
    moving = speed > STATIONARY_UM_S
    turn = np.zeros(0)
    if moving.sum() >= 3:
        # heading change between consecutive non-overlapping windows, per sqrt(s)
        sub = moving & ((ends - ends[0]) % win == 0)
        h = np.arctan2(vel[sub, 1], vel[sub, 0])
        fm = ends[sub]
        keep = np.diff(fm) == win
        dh = np.angle(np.exp(1j * np.diff(h)))[keep]
        turn = dh / math.sqrt(win * dt)
    path = float(speed.mean() * (f[-1] - f[0]) * dt) if len(speed) else 0.0
    net = float(np.linalg.norm(xy[-1] - xy[0])) if len(xy) > 1 else 0.0
    return {
        "frames": int(len(t)),
        "life_s": float((f[-1] - f[0] + 1) * dt),
        "speed_mean": float(speed.mean()) if len(speed) else 0.0,
        "speed_p50": float(np.median(speed)) if len(speed) else 0.0,
        "speed_p90": float(np.percentile(speed, 90)) if len(speed) else 0.0,
        "moving_frac": float(moving.mean()) if len(speed) else 0.0,
        "turn_sigma": float(np.std(turn)) if len(turn) >= 2 else 0.0,
        "tortuosity": float(path / net) if net > 1e-6 and path > 0 else float("inf"),
        "area_mean_px": float(t[:, 3].mean()),
    }


def match_species(
    t: np.ndarray, truth: dict[int, dict[int, tuple[float, float, str]]], match_px: float
) -> tuple[str, float]:
    """(species, fraction of frames matched) for the truth object this track rides."""
    votes: dict[str, int] = defaultdict(int)
    for f, x, y, _ in t:
        objs = truth.get(int(f), {})
        best, bd = None, match_px
        for _oid, (tx, ty, sp) in objs.items():
            d = math.hypot(x - tx, y - ty)
            if d < bd:
                best, bd = sp, d
        if best is not None:
            votes[best] += 1
    if not votes:
        return "unmatched", 0.0
    sp, n = max(votes.items(), key=lambda kv: kv[1])
    return sp, n / len(t)


def per_species(
    stats: dict[int, dict], labels: dict[int, str], min_frames: int = 10
) -> dict[str, dict]:
    """Frame-weighted speed and turn estimates per species, params-JSON shaped."""
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for tid, s in stats.items():
        sp = labels.get(tid, "unmatched")
        if s["frames"] < min_frames or sp == "unmatched":
            continue
        w = s["frames"]
        a = acc[sp]
        a["tracks"] += 1
        a["frames"] += w
        a["speed"] += w * s["speed_mean"]
        a["turn"] += w * s["turn_sigma"]
    out: dict[str, dict] = {}
    for sp, a in acc.items():
        out[sp] = {
            "tracks": int(a["tracks"]),
            "frames": int(a["frames"]),
            "motion": {
                "speed": round(a["speed"] / a["frames"], 1),
                "turn_sigma": round(a["turn"] / a["frames"], 3),
            },
        }
    return out


def _sidecar(csv_path: Path) -> dict:
    """``<stem>.json`` next to the clip, or the parameters block of ``<stem>_tracks.json``."""
    stem = csv_path.name.removesuffix("_tracks.csv")
    for cand in (csv_path.with_name(stem + ".json"), csv_path.with_name(stem + "_tracks.json")):
        if cand.exists():
            try:
                data = json.loads(cand.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                sc = data.get("sidecar") if "sidecar" in data else data
                if isinstance(sc, dict):
                    return sc
    return {}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("tracks", type=Path, help="<stem>_tracks.csv from track.py")
    p.add_argument("--um-per-px", type=float, help="scale (default: from the sidecar)")
    p.add_argument("--fps", type=float, help="frame rate (default: from the sidecar)")
    p.add_argument("--truth", type=Path, help="<stem>_truth.csv (default: next to the tracks)")
    p.add_argument("--match-px", type=float, default=25.0, help="truth match radius, px")
    p.add_argument("--min-frames", type=int, default=10, help="ignore shorter tracks")
    p.add_argument(
        "--window", type=float, default=0.2, help="seconds per velocity sample (jitter filter)"
    )
    p.add_argument("--json", type=Path, help="write the full report here")
    p.add_argument("--emit-params", type=Path, help="write per-species motion as a --params file")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        tracks = load_tracks(a.tracks)
    except (OSError, ValueError, KeyError) as e:
        print(f"trackstats: {e}", file=sys.stderr)
        return 2
    sc = _sidecar(a.tracks)
    um_per_px = a.um_per_px or sc.get("um_per_px")
    fps = a.fps or sc.get("fps")
    if not um_per_px or not fps or um_per_px <= 0 or fps <= 0:
        print("trackstats: need --um-per-px and --fps (no sidecar found)", file=sys.stderr)
        return 2
    if not tracks:
        print("trackstats: no tracks in file", file=sys.stderr)
        return 1
    n_frames = int(max(t[-1, 0] for t in tracks.values())) + 1
    win = max(1, int(round(a.window * fps)))
    drift = common_motion(tracks, n_frames, win)
    stats = {tid: track_stats(t, drift, um_per_px, fps, win) for tid, t in tracks.items()}
    truth_path = a.truth or a.tracks.with_name(
        a.tracks.name.removesuffix("_tracks.csv") + "_truth.csv"
    )
    labels: dict[int, str] = {}
    if truth_path.exists():
        truth = load_truth(truth_path)
        labels = {tid: match_species(t, truth, a.match_px)[0] for tid, t in tracks.items()}
    species = per_species(stats, labels, a.min_frames)
    known = drift[np.linalg.norm(drift, axis=1) > 0]
    drift_um_s = (
        float(np.median(np.linalg.norm(known, axis=1)) * um_per_px * fps) if len(known) else 0.0
    )
    long = {tid: s for tid, s in stats.items() if s["frames"] >= a.min_frames}
    report = {
        "tracks": len(tracks),
        "tracks_ge_min_frames": len(long),
        "um_per_px": um_per_px,
        "fps": fps,
        "drift_um_s": round(drift_um_s, 1),
        "drift_known_frac": round(float(len(known) / max(1, n_frames - win)), 3),
        "window_frames": win,
        "species": species,
        "per_track": {str(tid): {**s, "species": labels.get(tid, "")} for tid, s in stats.items()},
    }
    if a.json:
        a.json.write_text(json.dumps(report, indent=1) + "\n")
    if a.emit_params:
        a.emit_params.write_text(
            json.dumps({sp: {"motion": v["motion"]} for sp, v in species.items()}, indent=2) + "\n"
        )
    print(
        f"{a.tracks.name}: {len(tracks)} tracks ({len(long)} >= {a.min_frames} frames), "
        f"convection ~{drift_um_s:.0f} µm/s"
    )
    for sp, v in sorted(species.items(), key=lambda kv: -kv[1]["frames"]):
        m = v["motion"]
        print(
            f"  {sp:12s} {v['tracks']:3d} tracks {v['frames']:6d} frames  "
            f"speed {m['speed']:7.1f} µm/s  turn {m['turn_sigma']:.2f} rad/√s"
        )
    if not species:
        top = sorted(long.items(), key=lambda kv: -kv[1]["frames"])[:8]
        for tid, s in top:
            print(
                f"  track {tid:4d} {s['frames']:5d} f  speed {s['speed_mean']:7.1f} µm/s  "
                f"turn {s['turn_sigma']:.2f}  moving {s['moving_frac']:.2f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
