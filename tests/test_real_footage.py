"""Real microscope footage, opt in: `pytest --real-clips=data/real` after
scripts/real-clips.sh. Third-party YouTube clips, so they are cut locally and never
committed. Each case is a failure MOG2 showed on real footage; the mog2 bound is
asserted too, so a clip that stops being hard is noticed.

Measured (macOS, 2026-10-27): kvip hold 2 tracks / rotifer 246 of 246 frames, mog2
22 / 163. d3 hold 7, mog2 600. b4 hold 17, mog2 770. b3 0 and 0.
tomlov_swim (own footage, 2026-11-07): hold 6, swimmer passes 578 hits / 844 px net
and 304 / 272; mog2 36."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest
from conftest import TRACK, run_cli

pytestmark = [pytest.mark.real, pytest.mark.integration]


def _run(clip: Path, out: Path, bg: str, scale: str) -> dict:
    r = run_cli(TRACK, str(clip), "--bg", bg, "--scale", scale, "--no-video", "--out-dir", str(out))
    assert r.returncode == 0, r.stderr + r.stdout
    return json.loads((out / f"{clip.stem}_tracks.json").read_text())


def _longest(summary: dict) -> int:
    return max((t["hits"] for t in summary["tracks"]), default=0)


def test_rotifer_pausing_in_debris_keeps_one_id(real_clips, tmp_path):
    clip = real_clips / "kvip.mp4"
    hold = _run(clip, tmp_path / "hold", "hold", "1.0")
    mog = _run(clip, tmp_path / "mog2", "mog2", "1.0")
    assert hold["meta"]["frames"] == 246
    assert _longest(hold) >= 240, json.dumps(hold["tracks"], indent=1)
    assert hold["n_tracks_confirmed"] <= 4, json.dumps(hold["tracks"], indent=1)
    assert _longest(mog) < 200 and mog["n_tracks_confirmed"] >= 10, mog["n_tracks_confirmed"]


def _net_px(out: Path, stem: str) -> dict[int, float]:
    """Straight-line displacement, first to last row, per track id."""
    ends: dict[int, list[tuple[float, float]]] = {}
    with (out / f"{stem}_tracks.csv").open() as f:
        for row in csv.DictReader(f):
            p = (float(row["x"]), float(row["y"]))
            ends.setdefault(int(row["track_id"]), [p, p])[1] = p
    return {k: math.dist(a, b) for k, (a, b) in ends.items()}


def test_own_tomlov_swimmer_is_two_long_tracks(real_clips, tmp_path):
    """Our first own footage: TOMLOV, handheld then still, lamp glare in frame. One
    oval swimmer leaves through the top edge (frames ~40-347) and one (likely the
    same) re-enters and glides ~850 px down a curve (frames ~724-1319). The glare
    and the debris clump must not become tracks under hold."""
    clip = real_clips / "tomlov_swim.mp4"
    hold = _run(clip, tmp_path / "hold", "hold", "0.5")
    mog = _run(clip, tmp_path / "mog2", "mog2", "0.5")
    assert hold["meta"]["frames"] == 1320
    assert hold["sidecar"]["fps"] == 60, hold["sidecar"]
    net = _net_px(tmp_path / "hold", clip.stem)
    passes = sorted(
        ((t["hits"], net[t["id"]]) for t in hold["tracks"] if t["hits"] >= 250), reverse=True
    )
    dump = json.dumps(hold["tracks"], indent=1)
    assert len(passes) == 2, dump
    (glide_hits, glide_net), (exit_hits, exit_net) = passes
    assert glide_hits >= 520 and glide_net >= 750, dump
    assert exit_hits >= 270 and exit_net >= 240, dump
    assert hold["n_tracks_confirmed"] <= 10, dump
    assert mog["n_tracks_confirmed"] >= 20, mog["n_tracks_confirmed"]


@pytest.mark.parametrize(
    ("name", "hold_max", "mog_min"),
    [
        ("d3", 12, 100),  # darkfield, static debris: nothing in it swims
        ("b4", 40, 300),  # brightfield debris mat; its parked animal is a known miss
        ("b3", 0, 0),  # empty field: the negative control
    ],
)
def test_static_debris_does_not_become_tracks(real_clips, tmp_path, name, hold_max, mog_min):
    clip = real_clips / f"{name}.mp4"
    hold = _run(clip, tmp_path / "hold", "hold", "0.5")
    mog = _run(clip, tmp_path / "mog2", "mog2", "0.5")
    assert hold["n_tracks_confirmed"] <= hold_max, json.dumps(hold["tracks"], indent=1)
    assert mog["n_tracks_confirmed"] >= mog_min, mog["n_tracks_confirmed"]
