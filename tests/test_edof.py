"""edof.py: selection fusion takes each region from the camera that saw it sharp,
peak_z lands between planes when the energy says so, and end to end on an
ecosim multi-plane clip the fused frame beats every single camera and Z beats
guessing the middle of the chamber."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from conftest import REPO, run_cli

from edof import focus_measure, fuse, peak_z, score_frame

EDOF = REPO / "edof.py"
ECOSIM = REPO / "ecosim.py"


def _texture(seed: int = 0, size: int = 96) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.random((size, size)) * 200 + 20).astype(np.uint8)


def test_focus_measure_prefers_detail_over_blur():
    sharp = _texture()
    soft = cv2.GaussianBlur(sharp, (0, 0), 3)
    assert focus_measure(sharp, 9).mean() > 5 * focus_measure(soft, 9).mean()


def test_fuse_takes_each_half_from_the_plane_that_has_it_sharp():
    sharp = _texture()
    soft = cv2.GaussianBlur(sharp, (0, 0), 3)
    a = np.hstack([sharp[:, :48], soft[:, 48:]])  # camera 0: left in focus
    b = np.hstack([soft[:, :48], sharp[:, 48:]])  # camera 1: right in focus
    fused, idx, fm = fuse(np.stack([a, b]), 9)
    assert fm.shape == (2, 96, 96)
    assert (idx[:, :40] == 0).mean() > 0.95 and (idx[:, 56:] == 1).mean() > 0.95
    inner = np.s_[:, list(range(0, 40)) + list(range(56, 96))]
    assert np.array_equal(fused[inner], sharp[inner])  # copied, not synthesised


def test_fused_pixels_always_come_from_some_plane():
    rng = np.random.default_rng(3)
    stack = rng.integers(0, 256, (3, 40, 50), dtype=np.uint8)
    fused, idx, _ = fuse(stack, 5)
    picked = np.take_along_axis(stack, idx[None].astype(np.intp), axis=0)[0]
    assert np.array_equal(fused, picked)


@pytest.mark.parametrize("shape", [(96, 96), (1, 20, 20)])
def test_fuse_rejects_a_non_stack(shape):
    with pytest.raises(ValueError):
        fuse(np.zeros(shape, np.uint8), 9)


def test_peak_z_refines_between_planes():
    f = [50.0, 75.0, 100.0]
    assert peak_z(np.array([1.0, 3.0, 1.0]), f) == 75.0  # symmetric: on the plane
    z = peak_z(np.array([1.0, 3.0, 2.0]), f)
    assert 75.0 < z < 87.5  # leans toward the stronger neighbour, at most half a step
    q = [-((x - 80.0) ** 2) + 1e4 for x in f]  # exact parabola peaking at 80
    assert peak_z(np.array(q), f) == pytest.approx(80.0)
    assert peak_z(np.array([5.0, 1.0, 0.5]), f) == 50.0  # edge plane: no extrapolation
    with pytest.raises(ValueError):
        peak_z(np.array([1.0, 2.0]), f)


def test_score_frame_ignores_background_and_rewards_matching_the_oracle():
    oracle = np.full((60, 60), 18, np.uint8)
    oracle[20:40, 20:40] = _texture(size=20)
    noisy_bg = oracle.copy()
    noisy_bg[:10] = 200  # wrong only where the oracle is background
    blurred = cv2.GaussianBlur(oracle, (0, 0), 2)
    per, fu = score_frame(np.stack([noisy_bg, blurred]), oracle, oracle)
    assert per[0] == 99.0 == fu  # background error is outside the object mask
    assert per[1] is not None and per[1] < 30


# ---- end to end ----------------------------------------------------------------


@pytest.fixture(scope="module")
def stack_clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("edof")
    out = d / "st.mp4"
    r = run_cli(
        ECOSIM,
        "--out", str(out),
        "--frames", "30",
        "--size", "480x320",
        "--um-per-px", "0.6",
        "--na", "0.25",
        "--planes", "3",
        "--plane-spacing", "25",
        "--cast", "tetrahymena=6,coleps=1,euglena=2,debris=10",
        "--seed", "3",
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return out


@pytest.mark.integration
def test_ecosim_planes_write_cameras_oracle_and_sidecar(stack_clip):
    d = stack_clip.parent
    sc = json.loads(stack_clip.with_suffix(".json").read_text())
    assert [p["focus_um"] for p in sc["planes"]] == [50.0, 75.0, 100.0]
    assert sc["aif"] == "st_aif.mp4" and sc["dof_um"] == pytest.approx(8.8)
    assert not stack_clip.exists()  # N > 1: per-camera files instead of <out>
    for name in [p["file"] for p in sc["planes"]] + [sc["aif"]]:
        cap = cv2.VideoCapture(str(d / name))
        assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 30, name
        cap.release()


@pytest.mark.integration
def test_fusion_beats_every_camera_and_z_beats_guessing(stack_clip):
    r = run_cli(EDOF, str(stack_clip.with_suffix(".json")))
    assert r.returncode == 0, r.stderr
    d = stack_clip.parent
    rep = json.loads((d / "st_edof.json").read_text())
    assert (d / "st_edof.mp4").exists() and (d / "st_depth.mp4").exists()
    ps = rep["psnr_object_db"]
    assert ps["fused"] > max(ps["planes"]) + 0.5, ps
    z = rep["z"]["isolated"]
    assert z["samples"] > 50
    assert z["mae_inside_span_um"] < 0.5 * rep["spacing_um"], z  # sub-plane, 3 DoF apart
    assert z["mae_um"] < 0.75 * z["mae_guess_middle_um"], z


@pytest.mark.integration
@pytest.mark.parametrize("window", ["0", "4"])
def test_edof_rejects_bad_window(stack_clip, window):
    r = run_cli(EDOF, str(stack_clip.with_suffix(".json")), "--window", window)
    assert r.returncode == 2


@pytest.mark.integration
def test_edof_rejects_single_plane_and_missing_files(tmp_path):
    one = tmp_path / "one.json"
    one.write_text(json.dumps({"fps": 30, "planes": [{"file": "a.mp4", "focus_um": 75}]}))
    assert run_cli(EDOF, str(one)).returncode == 2
    gone = tmp_path / "gone.json"
    gone.write_text(
        json.dumps(
            {"planes": [{"file": "a.mp4", "focus_um": 50}, {"file": "b.mp4", "focus_um": 75}]}
        )
    )
    assert run_cli(EDOF, str(gone)).returncode == 2
    uneven = tmp_path / "uneven.json"
    uneven.write_text(
        json.dumps(
            {"planes": [{"file": f"{k}.mp4", "focus_um": z} for k, z in enumerate([0, 10, 40])]}
        )
    )
    assert run_cli(EDOF, str(uneven)).returncode == 2
    assert run_cli(EDOF, str(tmp_path / "nope.json")).returncode == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert run_cli(EDOF, str(bad)).returncode == 2
