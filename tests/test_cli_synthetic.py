"""End-to-end: synth.py -> track.py as subprocesses, scored against ground truth.
These are the G1 contract on synthetic data: stable IDs, a CSV, a follow clip."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest
from conftest import SYNTH, TRACK, read_tracks, read_truth, run_cli, score

pytestmark = pytest.mark.integration

SIZE = "320x240"
FPS = "30"


def synth(tmp: Path, name: str, *args: str) -> Path:
    out = tmp / f"{name}.mp4"
    r = run_cli(SYNTH, "--out", str(out), "--size", SIZE, "--fps", FPS, *args)
    assert r.returncode == 0, r.stderr
    return out


def track(video: Path, *args: str):
    r = run_cli(TRACK, str(video), "--min-area", "15", *args)
    assert r.returncode == 0, r.stderr + r.stdout
    stem = video.with_suffix("")
    return r, {
        "csv": Path(f"{stem}_tracks.csv"),
        "json": Path(f"{stem}_tracks.json"),
        "mp4": Path(f"{stem}_tracks.mp4"),
    }


WALK_SEED = "35"


@pytest.fixture(scope="module", params=["darkfield", "brightfield"])
def walk_case(request, tmp_path_factory) -> tuple[Path, str]:
    """Four swimmers that never come within 30 px of each other, so ID stability
    is a fair demand. (Crossings swap IDs by design; see the cross test.)
    Rendered in both illumination polarities: darkfield (bright on black) and
    brightfield (dark on white, the backlit TOMLOV)."""
    import numpy as np

    import synth as synth_mod

    pos = synth_mod.simulate(4, 150, (320, 240), 3.0, int(WALK_SEED))
    closest = min(
        np.linalg.norm(pos[:, i] - pos[:, j], axis=1).min()
        for i in range(4)
        for j in range(i + 1, 4)
    )
    assert closest > 30, f"seed {WALK_SEED} has a near-crossing at {closest:.1f} px"
    tmp = tmp_path_factory.mktemp(f"walk_{request.param}")
    clip = synth(
        tmp, "walk", "--n", "4", "--frames", "150", "--seed", WALK_SEED, "--polarity", request.param
    )
    return clip, request.param


@pytest.fixture(scope="module")
def walk_clip(walk_case) -> Path:
    return walk_case[0]


def test_walk_outputs_exist_with_schema_and_stable_ids(walk_case, frames_of):
    walk_clip, polarity = walk_case
    _, out = track(walk_clip)
    assert out["csv"].exists() and out["json"].exists() and out["mp4"].exists()

    with out["csv"].open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows and list(rows[0]) == ["frame", "t", "track_id", "x", "y", "area", "w", "h"]
    for r in rows:
        assert 0 <= int(r["frame"]) < 150
        assert 0 <= float(r["x"]) < 320 and 0 <= float(r["y"]) < 240
        assert float(r["area"]) >= 15 and int(r["w"]) >= 1 and int(r["h"]) >= 1
        assert abs(float(r["t"]) - int(r["frame"]) / 30) < 1e-3

    summary = json.loads(out["json"].read_text())
    assert summary["n_tracks_confirmed"] == 4, json.dumps(summary["tracks"], indent=1)
    assert summary["follow_id"] in {t["id"] for t in summary["tracks"]}
    assert summary["meta"]["frames"] == 150
    assert summary["meta"]["background"] == ("bright" if polarity == "brightfield" else "dark")
    assert summary["csv_rows"] == len(rows)
    assert summary["sidecar"] is None and summary["warnings"] == []

    s = score(read_truth(walk_clip.with_name("walk_truth.csv")), read_tracks(out["csv"]), 8.0)
    assert s["median_error"] < 2.0, s
    for oid, stab in s["stability"].items():
        assert stab > 0.9, (oid, s)

    n, w, h = frames_of(out["mp4"])
    assert (n, w, h) == (150, 320, 240)
    follow = walk_clip.with_name(f"walk_follow_{summary['follow_id']}.mp4")
    assert follow.exists(), summary["outputs"]
    assert summary["outputs"]["follow_video"] == follow.name
    n, w, h = frames_of(follow)
    assert (w, h) == (256, 256)
    ft = next(t for t in summary["tracks"] if t["id"] == summary["follow_id"])
    assert n == ft["life_frames"]


def test_scale_half_reports_full_res_coordinates(walk_clip, tmp_path):
    _, out = track(walk_clip, "--scale", "0.5", "--out-dir", str(tmp_path), "--no-video")
    out_csv = tmp_path / "walk_tracks.csv"
    assert out_csv.exists()
    assert not (tmp_path / "walk_tracks.mp4").exists()
    s = score(read_truth(walk_clip.with_name("walk_truth.csv")), read_tracks(out_csv), 8.0)
    assert s["median_error"] < 3.0, s
    assert s["n_errors"] > 0.9 * 4 * 150, s
    summary = json.loads((tmp_path / "walk_tracks.json").read_text())
    assert summary["params"]["scale"] == 0.5
    # follow clip still written in --no-video mode
    assert any(p.name.startswith("walk_follow_") for p in tmp_path.iterdir()), list(
        tmp_path.iterdir()
    )


def test_follow_explicit_id_and_missing_id(walk_clip, tmp_path):
    summary_path = walk_clip.with_name("walk_tracks.json")
    if not summary_path.exists():
        track(walk_clip)
    ids = [t["id"] for t in json.loads(summary_path.read_text())["tracks"]]
    chosen = ids[-1]
    _, _ = track(walk_clip, "--follow", str(chosen), "--out-dir", str(tmp_path), "--no-video")
    assert (tmp_path / f"walk_follow_{chosen}.mp4").exists()

    other = tmp_path / "missing"
    r, _ = track(walk_clip, "--follow", "9999", "--out-dir", str(other), "--no-video")
    assert "9999" in r.stderr and "warning" in r.stderr
    assert not list(other.glob("walk_follow_*")), list(other.iterdir())
    summary = json.loads((other / "walk_tracks.json").read_text())
    assert summary["follow_id"] is None and summary["warnings"]


def test_crossing_swimmers_stay_tracked_even_if_ids_swap(tmp_path):
    clip = synth(tmp_path, "cross", "--mode", "cross", "--frames", "80", "--speed", "2.5")
    _, out = track(clip, "--min-life", "10")
    summary = json.loads(out["json"].read_text())
    assert summary["n_tracks_confirmed"] >= 2, summary["tracks"]
    s = score(read_truth(clip.with_name("cross_truth.csv")), read_tracks(out["csv"]), 8.0)
    # Both objects are covered nearly every frame; identity may swap at the cross.
    for oid, cov in s["coverage"].items():
        assert cov > 0.85, (oid, s)
    assert s["median_error"] < 2.5, s


def test_static_scene_yields_no_tracks_and_no_follow(tmp_path):
    clip = synth(
        tmp_path, "static", "--mode", "static", "--n", "3", "--frames", "60", "--seed", "3"
    )
    r, out = track(clip)
    assert "0 confirmed tracks" in r.stdout
    with out["csv"].open() as fh:
        assert fh.read().strip() == "frame,t,track_id,x,y,area,w,h"
    assert not list(tmp_path.glob("static_follow_*"))
    summary = json.loads(out["json"].read_text())
    assert summary["n_tracks_confirmed"] == 0 and summary["follow_id"] is None
    assert summary["meta"]["frames"] == 60


def test_sidecar_is_embedded_and_bad_sidecar_is_a_warning(tmp_path):
    clip = synth(tmp_path, "side", "--n", "2", "--frames", "40", "--seed", "1")
    meta = {
        "date": "2026-10-25",
        "source_jar": "bedford-A",
        "objective": "4x",
        "notes": "ünïcode ✓ <script>",
    }
    clip.with_suffix(".json").write_text(json.dumps(meta))
    _, out = track(clip, "--no-video")
    assert json.loads(out["json"].read_text())["sidecar"] == meta

    clip.with_suffix(".json").write_text("{not json")
    r, out = track(clip, "--no-video")
    summary = json.loads(out["json"].read_text())
    assert summary["sidecar"] is None
    assert any("unreadable" in w for w in summary["warnings"]), summary["warnings"]
    assert "warning" in r.stderr

    clip.with_suffix(".json").write_text("[1,2,3]")
    _, out = track(clip, "--no-video")
    assert any("not a JSON object" in w for w in json.loads(out["json"].read_text())["warnings"])


def test_missing_file_is_a_clean_error(tmp_path):
    r = run_cli(TRACK, str(tmp_path / "nope.mp4"))
    assert r.returncode == 2
    assert "no such file" in r.stderr and "Traceback" not in r.stderr
    assert list(tmp_path.iterdir()) == []


def test_garbage_bytes_are_a_clean_error(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(os.urandom(4096))
    r = run_cli(TRACK, str(bad))
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "Traceback" not in r.stderr
    assert not (tmp_path / "bad_tracks.csv").exists()


def test_empty_file_is_a_clean_error(tmp_path):
    bad = tmp_path / "empty.mp4"
    bad.write_bytes(b"")
    r = run_cli(TRACK, str(bad))
    assert r.returncode == 2 and "Traceback" not in r.stderr


@pytest.mark.parametrize(
    "flag",
    [
        ["--scale", "0"],
        ["--scale", "1.5"],
        ["--scale", "-0.5"],
        ["--min-life", "0"],
        ["--history", "0"],
        ["--follow-size", "255"],
        ["--follow-size", "8"],
        ["--follow-smooth", "0"],
        ["--max-missed", "-1"],
        ["--assign", "hungarian"],
    ],
)
def test_invalid_flags_are_rejected_before_any_io(tmp_path, flag):
    r = run_cli(TRACK, str(tmp_path / "whatever.mp4"), *flag)
    assert r.returncode == 2 and "usage:" in r.stderr and "Traceback" not in r.stderr


def test_synth_rejects_bad_size_and_frames(tmp_path):
    r = run_cli(SYNTH, "--out", str(tmp_path / "x.mp4"), "--size", "10x10")
    assert r.returncode == 2 and "Traceback" not in r.stderr
    r = run_cli(SYNTH, "--out", str(tmp_path / "x.mp4"), "--size", "abc")
    assert r.returncode == 2 and "Traceback" not in r.stderr
    r = run_cli(SYNTH, "--out", str(tmp_path / "x.mp4"), "--frames", "0")
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_synth_is_deterministic(tmp_path):
    a = synth(tmp_path, "a", "--n", "3", "--frames", "20", "--seed", "5")
    b = synth(tmp_path, "b", "--n", "3", "--frames", "20", "--seed", "5")
    assert a.with_name("a_truth.csv").read_text() == b.with_name("b_truth.csv").read_text()
