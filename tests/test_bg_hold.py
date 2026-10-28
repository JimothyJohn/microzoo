"""--bg hold: the background model that keeps a swimmer that stops.

Each fixture here is a failure seen on real footage (a rotifer pausing in debris,
a defocus dip, a fragmenting blob) rebuilt synthetically so it runs in CI. The
pause fixture is checked to defeat MOG2 too, or it would prove nothing."""

from __future__ import annotations

import collections
import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest
from conftest import TRACK, read_tracks, read_truth, run_cli, score
from hypothesis import given, settings
from hypothesis import strategies as st

import ecosim
import synth
from track import HoldBackground, Track, _make_kalman, travel

# ----------------------------------------------------------------------------
# travel: how far a track has really gone


def _pts(xy: list[tuple[float, float]]) -> list[tuple]:
    return [(f, float(x), float(y), 50.0, 8, 8) for f, (x, y) in enumerate(xy)]


def test_travel_is_zero_until_ten_points():
    assert travel(_pts([(0, 0), (100, 0)] * 4)) == 0.0
    assert travel(_pts([(0, 0)] * 10)) == 0.0


def test_travel_measures_a_straight_drift():
    # 3 px/frame for 30 frames: median of frames 0-9 is 13.5, of 20-29 is 73.5
    assert travel(_pts([(3.0 * i, 0.0) for i in range(30)])) == pytest.approx(60.0)


def test_travel_ignores_a_fragment_centroid_jumping_back_and_forth():
    # A blob that splits and re-merges throws its centroid +-25 px every frame;
    # the raw first-to-last distance says 50 px, the body has not moved.
    jitter = [(100.0 + (25.0 if i % 2 else -25.0), 80.0) for i in range(40)]
    assert math.dist(jitter[0], jitter[-1]) == 50.0
    assert travel(_pts(jitter)) < 20.0


@settings(max_examples=200, deadline=None)
@given(
    st.lists(
        st.tuples(st.floats(-1, 1), st.floats(-1, 1)).filter(lambda p: p[0] ** 2 + p[1] ** 2 <= 1),
        min_size=10,
        max_size=80,
    ),
    st.floats(0, 40),
    st.floats(-1e4, 1e4),
    st.floats(-1e4, 1e4),
)
def test_travel_of_points_inside_a_disc_is_bounded_by_the_disc(unit, r, cx, cy):
    """Whatever a stationary body's centroid does inside radius r, travel stays within
    the per-axis median bound 2*sqrt(2)*r, and it does not depend on where the disc is."""
    pts = [(cx + r * u, cy + r * v) for u, v in unit]
    t = travel(_pts(pts))
    assert t <= 2 * math.sqrt(2) * r + 1e-6
    assert travel(_pts([(x - cx, y - cy) for x, y in pts])) == pytest.approx(t, abs=1e-6)


# ----------------------------------------------------------------------------
# HoldBackground as a unit


def _track(tid: int, xy: list[tuple[float, float]], w: int = 16, h: int = 16) -> Track:
    t = Track(id=tid, first_frame=0, last_frame=len(xy) - 1, kf=_make_kalman(*xy[0], 1e-2, 1.0))
    t.points = [(f, float(x), float(y), float(w * h), w, h) for f, (x, y) in enumerate(xy)]
    return t


def _noisy(img: np.ndarray, rng: np.random.Generator, sigma: float = 2.0) -> np.ndarray:
    return np.clip(img + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


def test_a_track_that_proved_it_moves_keeps_its_hold_back_at_its_birth_spot():
    hb = HoldBackground()
    out = [(10.0 + 3 * i, 50.0) for i in range(20)]  # 60 px out
    back = list(reversed(out))  # and home again
    t = _track(1, out)
    assert hb.holding([t]) == {1}
    t.points = _track(1, out + back).points
    assert travel(t.points) < 20.0  # first and last ten are both at home
    assert hb.holding([t]) == {1}


def test_a_jittering_fragment_never_earns_a_hold():
    hb = HoldBackground()
    t = _track(2, [(100.0 + (25.0 if i % 2 else -25.0), 80.0) for i in range(200)])
    assert hb.holding([t]) == set()


def test_seed_median_votes_out_a_swimmer_that_crosses_the_seed_window():
    rng = np.random.default_rng(1)
    base = np.full((60, 80), 120.0, np.float32)
    hb = HoldBackground(seed_frames=21)
    for i in range(21):
        f = base.copy()
        cv2.circle(f, (5 + 3 * i, 30), 4, 40, -1)  # moves its own width every 3 frames
        assert hb.add_seed(_noisy(f, rng)) == (i == 20)
    assert (hb.foreground(_noisy(base, rng)) == 0).all()
    probe = base.copy()
    cv2.circle(probe, (40, 30), 4, 40, -1)
    fg = hb.foreground(_noisy(probe, rng))
    assert fg[30, 40] == 255 and (fg > 0).sum() >= 30


def test_held_blob_stays_foreground_while_an_unheld_one_is_learned():
    """The contract that fixes the pausing rotifer: a body under a track that has
    proven it moves is never learned, however long it sits; the same body with no
    such track (debris that appeared) becomes background."""
    rng = np.random.default_rng(2)
    base = np.full((100, 160), 200.0, np.float32)
    hb = HoldBackground(seed_frames=10)
    for _ in range(10):
        hb.add_seed(_noisy(base, rng))
    scene = base.copy()
    cv2.rectangle(scene, (30, 40), (45, 55), 60, -1)  # A: the paused swimmer
    cv2.rectangle(scene, (110, 40), (125, 55), 60, -1)  # B: settled debris
    swim_in = [(3.0 * i - 30.0, 47.5) for i in range(23)]  # swam 66 px in from the left
    for frame in range(400):
        g = _noisy(scene, rng)
        fg = hb.foreground(g)
        a = _track(7, [*swim_in, *[(37.5, 47.5)] * (frame + 1)])
        a.points = [(frame - len(a.points) + 1 + k, *p[1:]) for k, p in enumerate(a.points)]
        hb.learn(g, fg, [a], frame, 1.0)
    fg = hb.foreground(_noisy(scene, rng))
    assert (fg[41:55, 31:45] > 0).mean() > 0.95
    assert (fg[41:55, 111:125] > 0).mean() < 0.05


def test_a_focus_jump_is_relearned_within_a_few_frames():
    """A Z move blurs every static edge at once. Off any held track the model should
    catch up in a handful of frames, not the ~100 its normal learning rate needs."""

    def run(focus_jump: float) -> list[float]:
        rng = np.random.default_rng(0)
        tex = cv2.GaussianBlur(rng.uniform(40, 220, (120, 160)).astype(np.float32), (0, 0), 1.0)
        blur = cv2.GaussianBlur(tex, (0, 0), 4.0)
        hb = HoldBackground(seed_frames=20, focus_jump=focus_jump, edge_px=0.0)
        for _ in range(20):
            hb.add_seed(_noisy(tex, rng))
        for f in range(12):
            g = _noisy(tex, rng)
            hb.learn(g, hb.foreground(g), [], f, 1.0)
        frac = []
        for f in range(12, 30):
            g = _noisy(blur, rng)
            fg = hb.foreground(g)
            frac.append(float((fg > 0).mean()))
            hb.learn(g, fg, [], f, 1.0)
        return frac

    boosted, plain = run(0.15), run(math.inf)
    assert boosted[0] > 0.2  # the jump really does light up the frame
    assert boosted[5] < 0.005, boosted
    assert plain[5] > 0.03, plain  # the boost is what did it


def test_edge_term_absorbs_a_subpixel_shift_of_textured_debris():
    rng = np.random.default_rng(3)
    # sharp-edged debris texture (a darkfield field of specks), shifted by 0.7 px
    tex = cv2.GaussianBlur(rng.uniform(40, 220, (120, 160)).astype(np.float32), (0, 0), 0.7)
    shift = np.array([[1, 0, 0.7], [0, 1, 0.4]], dtype=np.float32)
    shifted = cv2.warpAffine(tex, shift, (160, 120))
    fracs = {}
    for edge in (0.0, 2.0):
        hb = HoldBackground(seed_frames=20, edge_px=edge)
        for _ in range(20):
            hb.add_seed(_noisy(tex, rng))
        fracs[edge] = float((hb.foreground(_noisy(shifted, rng)) > 0)[8:-8, 8:-8].mean())
    assert fracs[0.0] > 0.2, fracs  # 0.42 here: every edge lights up
    assert fracs[2.0] < 0.02, fracs  # 0.008: a fifty-fold cut


def test_misuse_is_a_clear_error():
    with pytest.raises(ValueError):
        HoldBackground(seed_frames=0)
    hb = HoldBackground()
    frame = np.zeros((10, 10), np.uint8)
    with pytest.raises(RuntimeError):
        hb.foreground(frame)
    with pytest.raises(RuntimeError):
        hb.learn(frame, frame, [], 0, 1.0)
    with pytest.raises(ValueError):
        hb.build()
    hb.add_seed(frame)
    hb.build()
    with pytest.raises(ValueError):
        hb.foreground(np.zeros((10, 11), np.uint8))


# ----------------------------------------------------------------------------
# End to end: track.py --bg hold


def _track_cli(clip: Path, *args: str, out_dir: Path | None = None) -> tuple[dict, Path]:
    out = out_dir or clip.parent
    extra = ["--out-dir", str(out)] if out_dir else []
    r = run_cli(TRACK, str(clip), "--min-area", "15", "--no-video", *extra, *args)
    assert r.returncode == 0, r.stderr + r.stdout
    stem = out / clip.stem
    return json.loads(Path(f"{stem}_tracks.json").read_text()), Path(f"{stem}_tracks.csv")


def _pause_positions(frames: int = 260, move: int = 50, pause: int = 160) -> np.ndarray:
    """One swimmer: 3 px/frame for ``move`` frames, still for ``pause`` (over 5 s at
    30 fps), then off again. Plus one piece of debris that never moves."""
    x, xs = 40.0, []
    for f in range(frames):
        if not move <= f < move + pause:
            x += 3.0
        xs.append(x)
    swimmer = np.stack([np.array(xs), np.full(frames, 120.0)], axis=1)
    debris = np.tile(np.array([[250.0, 60.0]]), (frames, 1))
    return np.stack([swimmer, debris], axis=1)


@pytest.mark.integration
@pytest.mark.parametrize("polarity", ["darkfield", "brightfield"])
def test_a_swimmer_that_pauses_for_five_seconds_keeps_one_id(tmp_path, polarity):
    clip = tmp_path / "pause.mp4"
    synth.write_clip(clip, _pause_positions(), (320, 240), 30.0, 6.0, 7, polarity=polarity)
    truth = read_truth(tmp_path / "pause_truth.csv")
    swimmer = {f: {0: objs[0]} for f, objs in truth.items()}

    mog, mog_csv = _track_cli(clip, "--bg", "mog2", out_dir=tmp_path / "mog2")
    s_mog = score(swimmer, read_tracks(mog_csv), 8.0)
    # the fixture is only worth something if the old model fails it
    assert s_mog["stability"].get(0, 0.0) < 0.5, (s_mog, mog["tracks"])

    hold, hold_csv = _track_cli(clip, "--bg", "hold")
    s = score(swimmer, read_tracks(hold_csv), 8.0)
    assert s["stability"][0] > 0.9, (s, hold["tracks"])
    assert s["median_error"] < 2.0, s
    assert hold["n_tracks_confirmed"] == 1, json.dumps(hold["tracks"], indent=1)
    assert hold["meta"]["bg"] == "hold" and hold["meta"]["thresh"] == 9.0
    assert mog["meta"]["bg"] == "mog2" and mog["meta"]["thresh"] == 16.0


@pytest.mark.integration
@pytest.mark.parametrize("polarity", ["darkfield", "brightfield"])
@pytest.mark.parametrize("frames", [150, 40])
def test_walk_is_tracked_from_frame_zero_even_when_the_clip_is_shorter_than_the_seed(
    tmp_path, polarity, frames
):
    """The seed window is replayed once the background exists, so tracks start at
    frame 0; a 40-frame clip (shorter than --bg-seed 60) seeds from what it has."""
    pos = synth.simulate(4, frames, (320, 240), 3.0, 35)
    clip = tmp_path / "walk.mp4"
    synth.write_clip(clip, pos, (320, 240), 30.0, 6.0, 35, polarity=polarity)
    summ, csv_path = _track_cli(clip, "--bg", "hold", "--min-life", "10")
    assert summ["n_tracks_confirmed"] == 4, json.dumps(summ["tracks"], indent=1)
    assert min(t["first_frame"] for t in summ["tracks"]) == 0
    s = score(read_truth(tmp_path / "walk_truth.csv"), read_tracks(csv_path), 8.0)
    assert s["median_error"] < 2.0, s
    for oid, stab in s["stability"].items():
        assert stab > 0.9, (oid, s)


@pytest.mark.integration
@pytest.mark.parametrize("polarity", ["darkfield", "brightfield"])
def test_static_scene_yields_no_tracks(tmp_path, polarity):
    pos = synth.simulate(3, 60, (320, 240), 0.0, 3)
    clip = tmp_path / "static.mp4"
    synth.write_clip(clip, pos, (320, 240), 30.0, 6.0, 3, polarity=polarity)
    summ, _ = _track_cli(clip, "--bg", "hold")
    assert summ["n_tracks_confirmed"] == 0, summ["tracks"]


@pytest.mark.integration
@pytest.mark.parametrize("polarity", ["darkfield", "brightfield"])
def test_a_z_step_mid_clip_makes_no_debris_tracks_and_keeps_the_paramecia(tmp_path, polarity):
    """An autofocus hunt in a still chamber: focus jumps 60 µm for 20 frames and
    back. Every static edge changes at once; nothing that never moved may become a
    track, and every Paramecium stays covered through it."""
    um, size = 4.0, (400, 300)
    world = ecosim.World(
        {"paramecium": 4, "debris": 30},
        (size[0] * um, size[1] * um),
        seed=11,
        depth_um=150.0,
        drift_um_s=0.0,
    )
    rng = np.random.default_rng(5)
    clip = tmp_path / "zstep.mp4"
    wr = cv2.VideoWriter(str(clip), cv2.VideoWriter.fourcc(*"mp4v"), 30.0, size)
    truth: dict[int, dict[int, tuple[float, float]]] = collections.defaultdict(dict)
    home = world.focus
    for f in range(240):
        world.focus = home + 60.0 if 140 <= f < 160 else home
        wr.write(ecosim.render(world, size, um, polarity, rng))
        for row in world.truth_rows(um):
            if row[4] == "paramecium":
                truth[f][int(row[1])] = (float(row[2]), float(row[3]))
        world.step(1 / 30)
    wr.release()

    summ, csv_path = _track_cli(clip, "--bg", "hold", "--min-area", "20")
    tracks = read_tracks(csv_path)
    s = score(truth, tracks, 30.0)
    assert len(s["coverage"]) == 4, s
    for oid in s["coverage"]:
        assert s["coverage"][oid] > 0.85, (oid, s)
        # MOG2 on this clip: 0.28..0.46 (pass-overs in a 150 µm chamber dominate)
        assert s["stability"][oid] > 0.3, (oid, s)
    near: dict[int, list[float]] = collections.defaultdict(list)
    for f, objs in tracks.items():
        for tid, (x, y) in objs.items():
            near[tid].append(
                min((math.hypot(x - tx, y - ty) for tx, ty in truth[f].values()), default=1e9)
            )
    junk = [tid for tid, d in near.items() if float(np.median(d)) > 30]
    assert junk == [], (junk, summ["tracks"])
