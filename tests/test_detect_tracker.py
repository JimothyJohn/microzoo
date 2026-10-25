"""Unit tests for detect() and the Tracker state machine, no video I/O."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from track import Detection, Tracker, detect


def _mask(size=(200, 100), blobs=()):
    """blobs: (cx, cy, r) circles drawn white on a black mask (w, h) = size."""
    w, h = size
    m = np.zeros((h, w), dtype=np.uint8)
    for cx, cy, r in blobs:
        cv2.circle(m, (cx, cy), r, 255, -1)
    return m


def test_detect_empty_mask():
    assert detect(_mask(), 1, 1e9) == []


def test_detect_centroid_and_area_filters():
    m = _mask(blobs=[(50, 50, 5), (150, 50, 20)])
    all_dets = sorted(detect(m, 1, 1e9), key=lambda d: d.x)
    assert len(all_dets) == 2
    assert abs(all_dets[0].x - 50) < 1 and abs(all_dets[0].y - 50) < 1
    assert abs(all_dets[1].x - 150) < 1
    assert all_dets[0].area < all_dets[1].area
    # min_area drops the small one, max_area drops the big one.
    assert [d.x for d in detect(m, 200, 1e9)] == pytest.approx([150], abs=1)
    assert [d.x for d in detect(m, 1, 200)] == pytest.approx([50], abs=1)


def test_detect_scales_back_to_full_res():
    m = _mask(blobs=[(50, 25, 5)])
    full = detect(m, 1, 1e9, inv_scale=1.0)[0]
    half = detect(m, 1, 1e9, inv_scale=2.0)[0]
    assert half.x == pytest.approx(full.x * 2) and half.y == pytest.approx(full.y * 2)
    assert half.area == pytest.approx(full.area * 4)
    assert half.w == pytest.approx(full.w * 2, abs=1)
    # Area thresholds are in full-res units: a 5px-radius blob at half scale is
    # ~4*78 px^2 full-res, so min_area=200 keeps it; 400 drops it.
    assert len(detect(m, 200, 1e9, inv_scale=2.0)) == 1
    assert len(detect(m, 400, 1e9, inv_scale=2.0)) == 0


def test_detect_rejects_non_binary_garbage_without_crashing():
    noise = np.random.default_rng(0).integers(0, 256, (100, 200), dtype=np.uint8)
    dets = detect(noise, 1, 1e9)
    assert all(d.area >= 1 and d.w >= 1 and d.h >= 1 for d in dets)


def _d(x, y):
    return Detection(x=x, y=y, area=50.0, w=8, h=8)


def test_tracker_follows_a_constant_velocity_target():
    tr = Tracker(max_dist=10, max_missed=3)
    for f in range(30):
        tr.step(f, [_d(10 + 3 * f, 20 + 1 * f)])
    tracks = tr.all_tracks()
    assert len(tracks) == 1
    t = tracks[0]
    assert t.id == 1 and t.first_frame == 0 and t.last_frame == 29 and t.hits == 30
    px, py = t.predicted_xy()
    assert px == pytest.approx(10 + 3 * 29, abs=1.5)
    assert py == pytest.approx(20 + 29, abs=1.5)


def test_tracker_bridges_short_gaps_and_dies_after_max_missed():
    tr = Tracker(max_dist=15, max_missed=3)
    for f in range(10):
        tr.step(f, [_d(4 * f, 0)])
    for f in range(10, 13):  # 3 missed frames: still alive
        tr.step(f, [])
    assert len(tr.live) == 1 and tr.live[0].missed == 3
    tr.step(13, [_d(4 * 13, 0)])  # reacquired along the predicted line
    assert len(tr.all_tracks()) == 1 and tr.live[0].missed == 0
    for f in range(14, 18):
        tr.step(f, [])
    assert tr.live == [] and len(tr.dead) == 1


def test_tracker_new_ids_for_far_detections_and_ids_never_reused():
    tr = Tracker(max_dist=10, max_missed=0)
    tr.step(0, [_d(0, 0)])
    tr.step(1, [_d(100, 100)])  # too far: old track dies, new id
    tr.step(2, [_d(0, 0)])  # original spot again: still a new id
    ids = [t.id for t in tr.all_tracks()]
    assert ids == [1, 2, 3]


def test_tracker_two_targets_keep_separate_ids_when_apart():
    tr = Tracker(max_dist=10, max_missed=2)
    for f in range(40):
        tr.step(f, [_d(2 * f, 0), _d(2 * f, 100)])
    tracks = tr.all_tracks()
    assert len(tracks) == 2
    assert all(t.hits == 40 for t in tracks)
    ys = sorted(round(t.points[-1][2]) for t in tracks)
    assert ys == [0, 100]


def test_tracker_handles_empty_frames_from_the_start():
    tr = Tracker(max_dist=10, max_missed=2)
    for f in range(5):
        tr.step(f, [])
    assert tr.all_tracks() == []


def test_blob_fragment_does_not_spawn_a_track_that_steals_the_real_one():
    """Regression: a swimmer's blob split in two for one frame; the fragment became a
    new track, which then out-competed the established track and killed it."""
    tr = Tracker(max_dist=40, max_missed=10)
    for f in range(20):
        tr.step(f, [_d(100 + 3 * f, 50)])
    # frame 20: two fragments 8 px apart, both near the prediction (160, 50)
    tr.step(20, [_d(156, 50), _d(164, 50)])
    for f in range(21, 40):
        tr.step(f, [_d(100 + 3 * f, 50)])
    tracks = tr.all_tracks()
    assert len(tracks) == 1, [(t.id, t.first_frame, t.last_frame, t.hits) for t in tracks]
    assert tracks[0].id == 1 and tracks[0].last_frame == 39 and tracks[0].hits == 40


def test_birth_exclusion_still_allows_a_genuinely_separate_target():
    tr = Tracker(max_dist=40, max_missed=10, birth_dist=20)
    for f in range(10):
        tr.step(f, [_d(100, 50)])
    for f in range(10, 30):  # second target appears 25 px away: outside the exclusion
        tr.step(f, [_d(100, 50), _d(125, 50)])
    assert len(tr.all_tracks()) == 2
