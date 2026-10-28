"""Real microscope footage, opt in: `pytest --real-clips=data/real` after
scripts/real-clips.sh. Third-party YouTube clips, so they are cut locally and never
committed. Each case is a failure MOG2 showed on real footage; the mog2 bound is
asserted too, so a clip that stops being hard is noticed.

Measured (macOS, 2026-10-27): kvip hold 2 tracks / rotifer 246 of 246 frames, mog2
22 / 163. d3 hold 7, mog2 600. b4 hold 17, mog2 770. b3 0 and 0."""

from __future__ import annotations

import json
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
