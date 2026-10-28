"""stagesim.py end to end: the table's numbers, and the camera under a moving stage."""

from __future__ import annotations

import csv
import json

import pytest
from conftest import REPO, run_cli

STAGESIM = REPO / "stagesim.py"
pytestmark = pytest.mark.integration
SMALL = ["--size", "320x200", "--world", "2400x1800"]


def _rows(path):
    with path.open() as fh:
        return list(csv.DictReader(fh))


def test_table_numbers():
    r = run_cli(STAGESIM, "table", "--speed", "5000", "--acc", "50000")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    # same optics as hardware/HARDWARE.md §4 (AR0234 via the 0.5x relay)
    first = out.split("Z-stack")[0]  # the stack section reuses the view names
    row = {line.split("|")[1].strip(): line for line in first.splitlines() if line.startswith("| ")}
    assert "| 0.6 | 1.15 × 0.72 | 11.2 | 8.3 px | 45% | 0.30 mm/s |" in row["10x NA 0.25"]
    assert "| 0.15 | 0.29 × 0.18 | 1.5 | 33.3 px | 326% | 0.07 mm/s |" in row["40x NA 0.65"]
    # the 1 m/s³ jerk limit's 25 ms of filter delay is what loses it at 40x (90 ms to escape)
    assert row["paramecium"].count("yes") == 3
    assert "no:" in row["paramecium"].split("|")[-2]
    assert "no:" in row["didinium"]  # 1.6 mm/s escapes a 40x field before 50 mm/s² catches up
    assert "2.3 ms" in out  # sealed 150 µm chamber's viscous time


def test_table_more_acceleration_follows_more():
    # jerk off: at fixed jerk, more acceleration only lengthens the ramp (acc/jerk)
    lo = run_cli(STAGESIM, "table", "--acc", "20000", "--jerk", "0").stdout
    hi = run_cli(STAGESIM, "table", "--acc", "2000000", "--jerk", "0").stdout
    assert hi.count("yes") > lo.count("yes")


def test_table_jerk_limit_trades_settle_for_lag():
    smooth = run_cli(STAGESIM, "table").stdout
    sharp = run_cli(STAGESIM, "table", "--jerk", "0").stdout

    def settle_ms(out, view):
        line = next(x for x in out.splitlines() if x.startswith(f"| {view}"))
        return float(line.split("|")[8].split("+")[1].split("ms")[0])

    assert settle_ms(smooth, "10x") < settle_ms(sharp, "10x") / 3
    assert smooth.count("yes") < sharp.count("yes")


@pytest.mark.parametrize(
    "args",
    [
        ["table", "--acc", "0"],
        ["table", "--exposure", "2"],
        ["table", "--flex-zeta", "1.5"],
        ["table", "--jerk", "-1"],
        ["run", "--out", "x.mp4", "--objective", "100x"],
        ["run", "--out", "x.mp4", "--frames", "0"],
        ["run", "--out", "x.mp4", "--mode", "scan", "--tiles", "50x50", *SMALL],
        ["run", "--out", "x.mp4", "--world", "3000"],
    ],
)
def test_bad_args_exit_2(args, tmp_path):
    r = run_cli(STAGESIM, *args, cwd=tmp_path)
    assert r.returncode == 2, (r.stdout, r.stderr)


def test_follow_keeps_paramecium_in_field(tmp_path):
    out = tmp_path / "f.mp4"
    r = run_cli(STAGESIM, "run", "--out", str(out), "--mode", "follow", "--frames", "90", *SMALL)
    assert r.returncode == 0, r.stderr
    side = json.loads(out.with_suffix(".json").read_text())
    assert side["follow"]["in_field"] >= 0.95
    rows = _rows(tmp_path / "f_stage.csv")
    assert len(rows) == 90
    assert max(float(x["speed_um_s"]) for x in rows) <= 5000 + 1e-6
    assert (tmp_path / "f_truth.csv").stat().st_size > 0


def test_follow_latency_hurts(tmp_path):
    def rms(latency):
        out = tmp_path / f"l{latency}.mp4"
        r = run_cli(
            STAGESIM, "run", "--out", str(out), "--mode", "follow", "--frames", "90",
            "--latency", latency, "--deadband", "0", *SMALL,
        )  # fmt: skip
        assert r.returncode == 0, r.stderr
        return json.loads(out.with_suffix(".json").read_text())["follow"]["rms_err_px"]

    assert rms("0.4") > 2 * rms("0.02")


def test_scan_moves_blurs_and_settles(tmp_path):
    out = tmp_path / "s.mp4"
    r = run_cli(
        STAGESIM, "run", "--out", str(out), "--mode", "scan", "--tiles", "2x1", "--frames", "90",
        "--dwell", "0.1", *SMALL,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    rows = _rows(tmp_path / "s_stage.csv")
    xs = [float(x["cmd_x"]) for x in rows]
    fw = 320 * 0.6 * 1920 / 320  # field width, µm
    assert min(xs) == pytest.approx(-fw / 2, abs=1)
    assert max(xs) == pytest.approx(fw / 2, abs=1)
    # mid-hop the slide runs 5 mm/s: 10 µm per 2 ms exposure = 2.8 px at 3.6 µm/px
    assert max(float(x["blur_px"]) for x in rows) > 2
    assert float(rows[-1]["blur_px"]) < 1  # parked at the end


def test_zsweep_runs_through_the_chamber(tmp_path):
    out = tmp_path / "z.mp4"
    r = run_cli(
        STAGESIM, "run", "--out", str(out), "--mode", "zsweep", "--zrate", "300",
        "--frames", "120", "--dwell", "0", *SMALL,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    zs = [float(x["cmd_z"]) for x in _rows(tmp_path / "z_stage.csv")]
    assert min(zs) == pytest.approx(0, abs=1)
    assert max(zs) == pytest.approx(150, abs=1)


def test_well_chamber_reports_its_lag(tmp_path):
    out = tmp_path / "w.mp4"
    r = run_cli(
        STAGESIM, "run", "--out", str(out), "--mode", "hold", "--chamber", "well",
        "--frames", "10", *SMALL,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    side = json.loads(out.with_suffix(".json").read_text())
    assert side["well_tau_s"] == pytest.approx(0.101, abs=0.001)
    assert side["robot"]["model"] == "Meca500"


ZSMALL = ["--size", "320x200", "--dwell", "0.02"]


def test_zstack_writes_edof_planes(tmp_path):
    out = tmp_path / "zs.mp4"
    r = run_cli(
        STAGESIM, "run", "--out", str(out), "--mode", "zstack", "--objective", "10x",
        "--z0", "40", "--z1", "100", *ZSMALL,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    side = json.loads(out.with_suffix(".json").read_text())
    planes = side["planes"]
    # edof.py's contract: evenly spaced, floor first, one readable clip per plane
    zs = [p["focus_um"] for p in planes]
    assert zs == sorted(zs) and zs[0] == 40
    assert all(abs((b - a) - 5.6) < 1e-3 for a, b in zip(zs, zs[1:], strict=False))
    assert len(planes) == side["zstack"]["slices"] == 11
    for p in planes:
        assert (tmp_path / p["file"]).stat().st_size > 0
    assert len(_rows(tmp_path / "zs_stage.csv")) == 11


def test_zstack_perfect_robot_is_exact_and_ordered(tmp_path):
    out = tmp_path / "p.mp4"
    r = run_cli(
        STAGESIM, "run", "--out", str(out), "--mode", "zstack", "--objective", "40x",
        "--z0", "60", "--z1", "70", "--repeat", "0", "--jitter", "0", *ZSMALL,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    s = json.loads(out.with_suffix(".json").read_text())["zstack"]
    assert s["z_err_rms_um"] < 0.1, s  # SimStage.idle's settle threshold: ringing < 0.1 µm
    assert s["slices_out_of_order"] == 0, s
    assert s["xy_wander_rms_px"] < 0.1, s


def test_zstack_at_40x_the_spec_scrambles_slices_and_registration_helps(tmp_path):
    out = tmp_path / "s.mp4"
    r = run_cli(
        STAGESIM, "run", "--out", str(out), "--mode", "zstack", "--objective", "40x",
        "--z0", "60", "--z1", "80", *ZSMALL,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    s = json.loads(out.with_suffix(".json").read_text())["zstack"]
    assert s["z_err_over_step"] > 1, s  # 1.4 µm scatter against 0.77 µm slices
    assert s["slices_out_of_order"] > 0, s
    assert s["registration_err_rms_px"] < s["xy_wander_rms_px"], s


@pytest.mark.parametrize(
    "extra",
    [
        ["--objective", "tomlov"],  # no depth of field to step by
        ["--zstep", "0.01"],  # 15000 slices
        ["--z0", "100", "--z1", "50"],
        ["--z1", "500"],  # above the chamber's soft limit
        ["--target", "hydra", "--cast", "paramecium=3"],
    ],
)
def test_zstack_bad_args_exit_2(extra, tmp_path):
    r = run_cli(
        STAGESIM, "run", "--out", "z.mp4", "--mode", "zstack", *ZSMALL, *extra, cwd=tmp_path
    )
    assert r.returncode == 2, (r.stdout, r.stderr)


def test_table_has_the_stack_section():
    out = run_cli(STAGESIM, "table").stdout
    stack = [x for x in out.split("Z-stack")[1].splitlines() if x.startswith("| ")]
    rows = {x.split("|")[1].strip(): x for x in stack}
    assert "| 0.77 | 196 | 180% |" in rows["40x NA 0.65"]
    assert "measure" in rows["40x NA 0.65"]
    assert "fine as specified" in rows["4x NA 0.10"]
