from __future__ import annotations

import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
TRACK = REPO / "track.py"
SYNTH = REPO / "synth.py"

sys.path.insert(0, str(REPO))


def run_cli(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a repo script as a subprocess, the way the Pi will."""
    return subprocess.run(
        [sys.executable, "-I", str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
    )


def read_truth(path: Path) -> dict[int, dict[int, tuple[float, float]]]:
    """truth csv -> {frame: {obj_id: (x, y)}}"""
    out: dict[int, dict[int, tuple[float, float]]] = defaultdict(dict)
    with path.open() as fh:
        for row in csv.DictReader(fh):
            out[int(row["frame"])][int(row["obj_id"])] = (float(row["x"]), float(row["y"]))
    return out


def read_tracks(path: Path) -> dict[int, dict[int, tuple[float, float]]]:
    """tracks csv -> {frame: {track_id: (x, y)}}"""
    out: dict[int, dict[int, tuple[float, float]]] = defaultdict(dict)
    with path.open() as fh:
        for row in csv.DictReader(fh):
            out[int(row["frame"])][int(row["track_id"])] = (float(row["x"]), float(row["y"]))
    return out


def score(
    truth: dict[int, dict[int, tuple[float, float]]],
    tracks: dict[int, dict[int, tuple[float, float]]],
    match_px: float,
) -> dict:
    """Per truth object: fraction of frames covered by its dominant track id,
    and the median position error over matched frames."""
    per_obj: dict[int, list[int]] = defaultdict(list)
    errors: list[float] = []
    for f, objs in truth.items():
        dets = tracks.get(f, {})
        for oid, (tx, ty) in objs.items():
            best = None
            for tid, (x, y) in dets.items():
                d = float(np.hypot(x - tx, y - ty))
                if d < match_px and (best is None or d < best[0]):
                    best = (d, tid)
            if best is not None:
                per_obj[oid].append(best[1])
                errors.append(best[0])
    n_frames = max(truth) + 1 if truth else 0
    stability = {}
    for oid, ids in per_obj.items():
        counts = defaultdict(int)
        for i in ids:
            counts[i] += 1
        dominant = max(counts.values())
        stability[oid] = dominant / n_frames
    return {
        "stability": stability,
        "coverage": {oid: len(ids) / n_frames for oid, ids in per_obj.items()},
        "median_error": float(np.median(errors)) if errors else float("nan"),
        "n_errors": len(errors),
    }


@pytest.fixture
def frames_of():
    import cv2

    def _count(path: Path) -> tuple[int, int, int]:
        cap = cv2.VideoCapture(str(path))
        assert cap.isOpened(), path
        n = 0
        shape = None
        while True:
            ok, f = cap.read()
            if not ok:
                break
            shape = f.shape
            n += 1
        cap.release()
        assert shape is not None, f"no frames in {path}"
        return n, shape[1], shape[0]

    return _count


def pytest_addoption(parser):
    parser.addoption(
        "--network",
        action="store_true",
        default=False,
        help="also run tests marked 'network' (live calls to ecotaxa.obs-vlfr.fr)",
    )
    parser.addoption(
        "--real-clips",
        default=None,
        metavar="DIR",
        help="also run tests marked 'real' against the clips scripts/real-clips.sh cut "
        "into DIR (third-party footage, never committed)",
    )


def pytest_collection_modifyitems(config, items):
    """Opt-in tests are deselected, not skipped: 'network' without --network, 'real'
    without --real-clips."""
    off = set()
    if not config.getoption("--network"):
        off.add("network")
    if not config.getoption("--real-clips"):
        off.add("real")
    keep, drop = [], []
    for item in items:
        (drop if any(item.get_closest_marker(m) for m in off) else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


@pytest.fixture
def real_clips(request) -> Path:
    d = Path(request.config.getoption("--real-clips"))
    assert d.is_dir(), f"--real-clips {d}: not a directory (run scripts/real-clips.sh)"
    return d
