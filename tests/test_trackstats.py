"""trackstats recovers known motion from hand-built tracks: speed, straightness,
turning, convection consensus, species matching."""

from __future__ import annotations

import csv
import math

import numpy as np
import pytest

from trackstats import (
    common_motion,
    load_tracks,
    load_truth,
    match_species,
    per_species,
    track_stats,
)


def _track(n: int, vx: float, vy: float, x0=100.0, y0=100.0, f0=0) -> np.ndarray:
    f = np.arange(n) + f0
    return np.stack([f, x0 + vx * np.arange(n), y0 + vy * np.arange(n), np.full(n, 40.0)], axis=1)


def test_straight_track_speed_and_straightness():
    t = _track(60, 2.0, 0.0)  # 2 px/frame
    s = track_stats(t, np.zeros((60, 2)), um_per_px=1.5, fps=30, win=3)
    assert s["speed_mean"] == pytest.approx(2 * 1.5 * 30, rel=1e-6)
    assert s["turn_sigma"] == pytest.approx(0.0, abs=1e-9)
    assert s["tortuosity"] == pytest.approx(1.0, rel=1e-3)
    assert s["moving_frac"] == 1.0 and s["frames"] == 60 and s["life_s"] == 2.0


def test_stationary_track_is_not_moving():
    t = _track(40, 0.0, 0.0)
    s = track_stats(t, np.zeros((40, 2)), 1.5, 30, win=3)
    assert s["speed_mean"] == 0.0 and s["moving_frac"] == 0.0
    assert s["tortuosity"] == float("inf")


def test_wiggly_track_has_turn_but_straight_does_not():
    f = np.arange(120)
    x = 100 + 3.0 * f
    y = 100 + 20 * np.sin(2 * math.pi * f / 30)
    wig = np.stack([f, x, y, np.full(120, 40.0)], axis=1)
    sw = track_stats(wig, np.zeros((120, 2)), 1.0, 30, win=3)
    ss = track_stats(_track(120, 3.0, 0.0), np.zeros((120, 2)), 1.0, 30, win=3)
    assert sw["turn_sigma"] > 1.0 > ss["turn_sigma"]
    assert sw["tortuosity"] > 1.05


def test_gaps_in_a_track_do_not_create_fake_speed():
    t = _track(30, 1.0, 0.0)
    t = np.concatenate([t[:10], _track(10, 1.0, 0.0, x0=500.0, f0=20)])  # jump across a gap
    s = track_stats(t, np.zeros((40, 2)), 1.0, 30, win=2)
    assert s["speed_mean"] == pytest.approx(30.0, rel=1e-6)  # 1 px/frame, never the jump


def test_common_motion_needs_consensus():
    drift = (0.8, -0.4)
    debris = {i: _track(50, *drift, x0=50 + 30 * i, y0=60 + 20 * i) for i in range(6)}
    cm = common_motion(debris, 50, win=5)
    assert np.allclose(cm[10:], drift)
    assert np.all(cm[:5] == 0)  # no full window yet
    swimmers = {
        10: _track(50, 5.0, 0.0),
        11: _track(50, 0.0, 5.0),
        12: _track(50, -5.0, 0.0),
        13: _track(50, 0.0, -5.0),
    }
    assert np.all(common_motion(swimmers, 50, win=5) == 0)  # four directions: no consensus
    assert np.all(common_motion({1: debris[1], 2: debris[2]}, 50, win=5) == 0)  # too few


def test_convection_is_subtracted_before_speed():
    drift = np.tile([1.0, 0.0], (60, 1))
    rider = _track(60, 1.0, 0.0)  # only moves with the current
    s = track_stats(rider, drift, 1.0, 30, win=3)
    assert s["speed_mean"] == pytest.approx(0.0, abs=1e-9) and s["moving_frac"] == 0.0


def test_match_species_votes_by_proximity(tmp_path):
    truth = tmp_path / "x_truth.csv"
    with truth.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "obj_id", "x", "y", "species"])
        for f in range(20):
            w.writerow([f, 1, 100 + f, 100, "paramecium"])
            w.writerow([f, 2, 300, 300 - f, "didinium"])
    tr = load_truth(truth)
    sp, frac = match_species(_track(20, 1.0, 0.0, x0=102, y0=101), tr, match_px=10)
    assert sp == "paramecium" and frac == 1.0
    assert match_species(_track(20, 0.0, 0.0, x0=900, y0=900), tr, 10)[0] == "unmatched"


def test_per_species_is_frame_weighted():
    stats = {
        1: {"frames": 100, "speed_mean": 1000.0, "turn_sigma": 1.0},
        2: {"frames": 50, "speed_mean": 400.0, "turn_sigma": 0.4},
        3: {"frames": 5, "speed_mean": 9999.0, "turn_sigma": 9.0},  # too short, ignored
        4: {"frames": 80, "speed_mean": 10.0, "turn_sigma": 0.0},  # unmatched, ignored
    }
    labels = {1: "paramecium", 2: "paramecium", 3: "paramecium"}
    out = per_species(stats, labels, min_frames=10)
    assert set(out) == {"paramecium"}
    assert out["paramecium"]["tracks"] == 2 and out["paramecium"]["frames"] == 150
    assert out["paramecium"]["motion"]["speed"] == pytest.approx(800.0)
    assert out["paramecium"]["motion"]["turn_sigma"] == pytest.approx(0.8)


def test_load_tracks_rejects_wrong_columns(tmp_path):
    bad = tmp_path / "bad_tracks.csv"
    bad.write_text("frame,id,x\n0,1,2\n")
    with pytest.raises(ValueError, match="expected columns"):
        load_tracks(bad)
    good = tmp_path / "good_tracks.csv"
    good.write_text("frame,t,track_id,x,y,area,w,h\n1,0.03,7,1,2,3,4,5\n0,0,7,0,0,3,4,5\n")
    t = load_tracks(good)
    assert list(t) == [7] and t[7][0, 0] == 0 and t[7][1, 0] == 1  # sorted by frame
