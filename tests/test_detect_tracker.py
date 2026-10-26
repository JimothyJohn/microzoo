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


def test_tracker_rejects_unknown_assigner_and_accepts_both_known_ones():
    with pytest.raises(ValueError, match="assign"):
        Tracker(max_dist=10, max_missed=3, assign="hungarian")
    for name in ("auction", "greedy"):
        tr = Tracker(max_dist=10, max_missed=3, assign=name)
        for f in range(5):
            tr.step(f, [_d(10 + 2 * f, 20)])
        assert len(tr.all_tracks()) == 1


def test_tracker_keeps_both_ids_when_a_fragment_tempts_the_neighbour():
    # Two tracks 6 px apart; a frame where A's detection is 2 px nearer to B than B's own
    # (B's blob split). Greedy would hand B the wrong blob and strand A for a frame.
    tr = Tracker(max_dist=10, max_missed=3, birth_dist=0, assign="auction")
    for f in range(10):
        tr.step(f, [_d(0.0, 0.0), _d(6.0, 0.0)])
    tr.step(10, [_d(2.5, 0.0), _d(7.0, 0.0)])
    ids = sorted(t.id for t in tr.live)
    assert ids == [1, 2]
    by_id = {t.id: t for t in tr.live}
    assert by_id[1].points[-1][1] == 2.5 and by_id[2].points[-1][1] == 7.0
    assert all(t.missed == 0 for t in tr.live)


def test_tracker_keeps_its_id_through_a_reversal():
    # 6 px/frame right for 20 frames, then an avoiding reaction: 4 px/frame back.
    # The constant-velocity prediction overshoots by 10 px a frame; gating on the last
    # measured position too keeps the detection within reach (max_dist 15).
    path = [(10.0 + 6 * f, 20.0) for f in range(20)]
    path += [(path[-1][0] - 4 * (k + 1), 20.0) for k in range(20)]
    tr = Tracker(max_dist=15, max_missed=2)
    for f, (x, y) in enumerate(path):
        tr.step(f, [_d(x, y)])
    assert len(tr.all_tracks()) == 1 and tr.all_tracks()[0].hits == 40
    v1 = Tracker(max_dist=15, max_missed=2, anchor_last=False)
    for f, (x, y) in enumerate(path):
        v1.step(f, [_d(x, y)])
    assert len(v1.all_tracks()) > 1  # the v1 behaviour: a new id after the turn


def test_debris_track_cannot_steal_a_passing_body():
    # A 30 px² speck sits still; a 1500 px² body sweeps past within max_dist while its own
    # track is momentarily unmatched. With the area gate the speck's track stays a speck.
    speck = Detection(x=50.0, y=50.0, area=30.0, w=6, h=6)
    tr = Tracker(max_dist=40, max_missed=3, birth_dist=0)
    for f in range(10):
        tr.step(f, [speck])
    body = Detection(x=70.0, y=55.0, area=1500.0, w=60, h=30)
    tr.step(10, [body])  # the speck vanished this frame; the body is 21 px away
    ids = {t.id: t for t in tr.live}
    assert ids[1].points[-1][3] == 30.0 and ids[1].missed == 1
    assert any(t.points[-1][3] == 1500.0 and t.id != 1 for t in tr.live)
    off = Tracker(max_dist=40, max_missed=3, birth_dist=0, area_ratio=0)
    for f in range(10):
        off.step(f, [speck])
    off.step(10, [body])
    assert off.live[0].id == 1 and off.live[0].points[-1][3] == 1500.0  # without the gate


def test_fragment_scale_suppresses_births_within_a_big_blob():
    big = Detection(x=100.0, y=100.0, area=1500.0, w=60, h=30)
    tr = Tracker(max_dist=40, max_missed=3, birth_dist=5, fragment_scale=0.6)
    for f in range(5):
        tr.step(f, [big])
    # the mask splits: the body's main part plus a chunk 28 px off-centre (> birth_dist)
    tr.step(5, [big, Detection(x=128.0, y=100.0, area=300.0, w=20, h=20)])
    assert len(tr.live) == 1
    loose = Tracker(max_dist=40, max_missed=3, birth_dist=5, fragment_scale=0.0)
    for f in range(5):
        loose.step(f, [big])
    loose.step(5, [big, Detection(x=128.0, y=100.0, area=300.0, w=20, h=20)])
    assert len(loose.live) == 2


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
