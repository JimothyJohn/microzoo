"""The loop, end to end: species.py numbers -> ecosim clip -> track.py ->
trackstats -> numbers again. Plus the CLIs' negative paths."""

from __future__ import annotations

import json
import subprocess

import pytest
from conftest import REPO, read_tracks, read_truth, run_cli, score

from species import load_params

ECOSIM = REPO / "ecosim.py"
SPRITES = REPO / "sprites.py"
STATS = REPO / "trackstats.py"
pytestmark = pytest.mark.integration


def _read_truth_species(path):
    import csv

    out = {}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            out[int(row["obj_id"])] = row["species"]
    return out


@pytest.fixture(scope="module")
def eco_clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("eco")
    out = d / "eco.mp4"
    r = run_cli(
        ECOSIM,
        "--out",
        str(out),
        "--frames",
        "180",
        "--fps",
        "30",
        "--size",
        "400x300",
        "--um-per-px",
        "4",
        "--seed",
        "11",
        "--cast",
        "paramecium=4,debris=30",
        "--drift",
        "30",
    )
    assert r.returncode == 0, r.stderr
    return out


def test_ecosim_writes_clip_truth_events_and_sidecar(eco_clip):
    truth = eco_clip.with_name("eco_truth.csv")
    events = eco_clip.with_name("eco_events.csv")
    sidecar = eco_clip.with_suffix(".json")
    assert truth.exists() and events.exists() and sidecar.exists()
    assert truth.read_text().splitlines()[0] == (
        "frame,obj_id,x,y,species,state,heading,length_px,z_um"
    )
    assert events.read_text().splitlines()[0] == "frame,t,kind,actor,subject,x,y"
    sc = json.loads(sidecar.read_text())
    assert sc["source"] == "ecosim" and sc["um_per_px"] == 4 and sc["fps"] == 30
    assert sc["cast"] == {"paramecium": 4, "debris": 30}
    assert sc["depth_um"] == 150 and sc["dof_um"] == 30 and sc["focus_um"] == 75
    assert sc["species"]["paramecium"]["motion"]["speed"] == 1000
    t = read_truth(truth)
    assert len(t) == 180 and len(t[0]) == 34


def test_tracker_follows_every_paramecium_through_the_debris(eco_clip):
    r = run_cli(REPO / "track.py", str(eco_clip), "--min-area", "20")
    assert r.returncode == 0, r.stderr
    truth_path = eco_clip.with_name("eco_truth.csv")
    truth = read_truth(truth_path)
    species = _read_truth_species(truth_path)
    paras = {oid for oid, sp in species.items() if sp == "paramecium"}
    only = {f: {o: xy for o, xy in objs.items() if o in paras} for f, objs in truth.items()}
    s = score(only, read_tracks(eco_clip.with_name("eco_tracks.csv")), match_px=30)
    assert set(s["coverage"]) == paras, s
    for oid in paras:
        assert s["coverage"][oid] > 0.7, (oid, s)
        # v1 greedy: 0.17..0.42. Auction + area gate + fragment rule + last-position
        # anchor: 0.27..0.63. With merge groups (velocity carried through a shared
        # blob): 0.25..0.41 in the flat sim, because every overlap is a bump and
        # the Paramecium reverses inside the merge, so extrapolation picks the wrong
        # body at the split. Coverage is the contract.
        assert s["stability"][oid] > 0.2, (oid, s)
    assert s["median_error"] < 4.0, s


def test_trackstats_recovers_the_speed_it_was_given(eco_clip):
    tracks = eco_clip.with_name("eco_tracks.csv")
    if not tracks.exists():
        r = run_cli(REPO / "track.py", str(eco_clip), "--min-area", "20")
        assert r.returncode == 0, r.stderr
    report = eco_clip.with_name("stats.json")
    params = eco_clip.with_name("fitted.json")
    r = run_cli(STATS, str(tracks), "--json", str(report), "--emit-params", str(params))
    assert r.returncode == 0, r.stderr
    rep = json.loads(report.read_text())
    assert rep["um_per_px"] == 4 and rep["fps"] == 30  # found the sidecar
    est = rep["species"]["paramecium"]["motion"]["speed"]
    assert 550 < est < 1150, rep["species"]  # model says 1000; individuals spread +-25 %
    assert 15 < rep["drift_um_s"] < 60, rep["drift_um_s"]  # the 30 µm/s current, from debris
    assert rep["drift_known_frac"] > 0.5
    fitted = load_params(params.read_text())  # the output is a valid --params file
    assert fitted["paramecium"].motion.speed == est


def test_brightfield_eco_clip_tracks_too(tmp_path):
    out = tmp_path / "bf.mp4"
    r = run_cli(
        ECOSIM, "--out", str(out), "--frames", "90", "--size", "320x240",
        "--polarity", "brightfield", "--cast", "paramecium=3,rotifer=1", "--seed", "5",
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    r = run_cli(REPO / "track.py", str(out), "--min-area", "20")
    assert r.returncode == 0, r.stderr
    rows = out.with_name("bf_tracks.csv").read_text().splitlines()
    assert len(rows) > 90


def test_params_override_reaches_the_sidecar(tmp_path):
    p = tmp_path / "p.json"
    p.write_text('{"paramecium": {"motion": {"speed": 123}}}')
    out = tmp_path / "x.mp4"
    r = run_cli(
        ECOSIM, "--out", str(out), "--frames", "3", "--size", "64x48",
        "--cast", "paramecium=1", "--params", str(p),
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    sc = json.loads(out.with_suffix(".json").read_text())
    assert sc["species"]["paramecium"]["motion"]["speed"] == 123


def test_dump_params_is_valid_json(tmp_path):
    r = run_cli(ECOSIM, "--dump-params")
    assert r.returncode == 0
    assert load_params(r.stdout)["didinium"].motion.strike_radius > 0


@pytest.mark.parametrize(
    "args",
    [
        ["--cast", "unicorn=1"],
        ["--cast", "paramecium=-2"],
        ["--frames", "0"],
        ["--um-per-px", "0"],
        ["--size", "10x10"],
        ["--polarity", "phase"],
        ["--depth", "-1"],
        ["--dof", "0"],
        ["--depth", "100", "--focus", "150"],
        ["--blur-um", "-5"],
    ],
)
def test_ecosim_rejects_bad_flags(tmp_path, args):
    r = run_cli(ECOSIM, "--out", str(tmp_path / "x.mp4"), *args)
    assert r.returncode == 2, (r.stdout, r.stderr)


def test_ecosim_rejects_bad_params_file(tmp_path):
    p = tmp_path / "p.json"
    p.write_text('{"paramecium": {"motion": {"warp": 1}}}')
    r = run_cli(ECOSIM, "--out", str(tmp_path / "x.mp4"), "--params", str(p))
    assert r.returncode == 2 and "warp" in r.stderr
    p.write_text("{nope")
    r = run_cli(ECOSIM, "--out", str(tmp_path / "x.mp4"), "--params", str(p))
    assert r.returncode == 2 and "params" in r.stderr
    r = run_cli(ECOSIM, "--out", str(tmp_path / "x.mp4"), "--params", str(tmp_path / "missing"))
    assert r.returncode == 2


def test_ecosim_needs_an_output():
    r = run_cli(ECOSIM)
    assert r.returncode == 2 and "--out" in r.stderr


def test_sprites_cli_writes_two_sheets_and_an_atlas(tmp_path):
    out = tmp_path / "s.png"
    r = run_cli(SPRITES, "--sheet", str(out), "--frames", "3", "--cell", "48")
    assert r.returncode == 0, r.stderr
    atlas = json.loads((tmp_path / "s.json").read_text())
    assert set(atlas["sheets"]) == {"darkfield", "brightfield"}
    for name in atlas["sheets"].values():
        assert (tmp_path / name).stat().st_size > 1000
    assert "debris" not in atlas["species"] and "paramecium" in atlas["species"]
    r = run_cli(SPRITES, "--sheet", str(out), "--species", "unicorn")
    assert r.returncode == 2
    r = run_cli(SPRITES, "--sheet", str(out), "--frames", "0")
    assert r.returncode == 2


def test_trackstats_without_a_sidecar_needs_scale_and_fps(tmp_path):
    csv_path = tmp_path / "lonely_tracks.csv"
    csv_path.write_text("frame,t,track_id,x,y,area,w,h\n0,0,1,0,0,9,3,3\n1,0.03,1,1,0,9,3,3\n")
    r = run_cli(STATS, str(csv_path))
    assert r.returncode == 2 and "--um-per-px" in r.stderr
    r = run_cli(STATS, str(csv_path), "--um-per-px", "2", "--fps", "30")
    assert r.returncode == 0, r.stderr
    r = run_cli(STATS, str(tmp_path / "missing.csv"), "--um-per-px", "2", "--fps", "30")
    assert r.returncode == 2
    garbage = tmp_path / "g_tracks.csv"
    garbage.write_bytes(b"\x00\xff\xfe,,,\n")
    r = run_cli(STATS, str(garbage), "--um-per-px", "2", "--fps", "30")
    assert r.returncode in (1, 2)


def test_scripts_run_under_isolated_python():
    # -I means no cwd on sys.path; the modules must still find each other
    r = subprocess.run(
        ["uv", "run", "python", "-I", str(ECOSIM), "--dump-params"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
