"""Behaviour contracts of the ecosystem sim, without video: determinism,
walls, the predator/prey state machine, Stentor's one-frame contraction,
rotifer release, and convection that moves debris but not the anchored."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ecosim import (
    DEFAULT_CAST,
    Organism,
    World,
    parse_cast,
    plane_focuses,
    render,
    render_planes,
)
from optics import Optics
from species import SPECIES, load_params
from sprites import stentor_length

SMALL = (900.0, 700.0)  # µm


def _run(world: World, seconds: float, fps: float = 30.0) -> None:
    for _ in range(int(seconds * fps)):
        world.step(1.0 / fps)


def test_parse_cast_accepts_counts_and_bare_names():
    cast = parse_cast("paramecium=3, didinium ,debris=0,paramecium=1", SPECIES)
    assert cast == {"paramecium": 4, "didinium": 1, "debris": 0}
    assert parse_cast(DEFAULT_CAST, SPECIES)["paramecium"] == 8


@pytest.mark.parametrize("bad", ["unicorn=2", "paramecium=x", "paramecium=-1", "=3"])
def test_parse_cast_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_cast(bad, SPECIES)


def test_world_is_seed_deterministic():
    cast = parse_cast(DEFAULT_CAST, SPECIES)
    a, b, c = (World(cast, (1800, 1400), seed=s) for s in (4, 4, 5))
    for w in (a, b, c):
        _run(w, 3)
    pa = np.array([o.pos for o in a.orgs])
    assert np.array_equal(pa, np.array([o.pos for o in b.orgs]))
    assert not np.array_equal(pa, np.array([o.pos for o in c.orgs]))
    assert [e.kind for e in a.events] == [e.kind for e in b.events]


def test_everyone_stays_in_the_chamber():
    cast = parse_cast("paramecium=6,didinium=2,stentor=2,rotifer=2,daphnia=1,debris=10", SPECIES)
    w = World(cast, (1800, 1400), seed=2)
    for _ in range(600):
        w.step(1 / 60)
        for o in w.orgs:
            assert -1 <= o.pos[0] <= w.w + 1 and -1 <= o.pos[1] <= w.h + 1, (o.species, o.pos)
            assert np.isfinite(o.heading)


def test_didinium_hunts_swallows_and_digests():
    w = World({"paramecium": 1, "didinium": 1}, SMALL, seed=1)
    prey = next(o for o in w.orgs if o.species == "paramecium")
    pred = next(o for o in w.orgs if o.species == "didinium")
    assert np.linalg.norm(prey.pos - pred.pos) > 0.5 * (prey.length_um + pred.length_um)
    captured = None
    for f in range(30 * 60):
        w.step(1 / 30)
        if w.events and captured is None:
            captured = f
            assert w.events[0].kind == "capture"
            assert prey.state == "caught" and pred.state == "ingest"
        if prey.state == "eaten":
            break
    assert captured is not None, "no capture in 60 s"
    assert not prey.visible
    kinds = [e.kind for e in w.events]
    assert kinds[:2] == ["capture", "ingested"]
    t_cap = w.events[0].t
    t_eat = w.events[1].t
    assert abs((t_eat - t_cap) - SPECIES["didinium"].motion.ingest_time) < 0.1
    assert pred.state == "digest" and pred.swell > 1.2
    assert all(r[1] != prey.id for r in w.truth_rows(3.0))  # eaten things leave the truth
    _run(w, SPECIES["didinium"].motion.digest_time + 0.5)
    assert pred.state == "swim" and pred.swell == 1.0


def test_prey_shrinks_into_the_snout_while_being_swallowed():
    w = World({"paramecium": 1, "didinium": 1}, SMALL, seed=1)
    prey = next(o for o in w.orgs if o.species == "paramecium")
    pred = next(o for o in w.orgs if o.species == "didinium")
    while not w.events:
        w.step(1 / 30)
    _run(w, SPECIES["didinium"].motion.ingest_time / 2)
    assert 0.3 < prey.shrink < 0.8
    assert np.linalg.norm(prey.pos - pred.pos) < pred.length_um


def test_stentor_contracts_in_one_frame_and_reextends_slowly():
    species = load_params('{"stentor": {"motion": {"contract_rate": 1000}}}')
    w = World({"stentor": 1}, (3000, 2400), seed=3, species=species)
    s = w.orgs[0]
    full = s.length_um
    assert s.contraction == 0.0 and s.anchor is not None
    w.step(1 / 60)
    assert s.contraction == 1.0 and w.events[0].kind == "contraction"
    row = w.truth_rows(1.0)[0]
    assert float(row[7]) == pytest.approx(full, abs=0.01)  # truth reports the resting length
    assert np.linalg.norm(s.pos - s.anchor) == pytest.approx(stentor_length(full, 1.0) / 2)
    # no second trigger while contracted, then a slow re-extension
    _run(w, 1.0, fps=60)
    assert len(w.events) == 1 and 0 < s.contraction < 1
    w.species = load_params('{"stentor": {"motion": {"contract_rate": 0}}}')  # calm down
    _run(w, SPECIES["stentor"].motion.reextend_time, fps=60)
    assert s.contraction == 0.0 and s.state == "extended"
    assert len(w.events) == 1


def test_stentor_contracts_when_a_swimmer_passes():
    species = load_params(
        '{"stentor": {"motion": {"contract_rate": 0}}, "paramecium": {"motion": {"speed": 0}}}'
    )
    w = World({"stentor": 1}, (3000, 2400), seed=3, species=species)
    s = w.orgs[0]
    _run(w, 2)
    assert not w.events
    o = w._spawn("paramecium")
    o.pos = s.anchor + np.array([math.cos(s.heading), math.sin(s.heading)]) * s.length_um
    w.step(1 / 30)
    assert s.contraction == 1.0 and w.events[-1].kind == "contraction"


def test_rotifer_lets_go_swims_and_reanchors():
    species = load_params('{"rotifer": {"motion": {"release_rate": 1000, "release_time": 1.0}}}')
    w = World({"rotifer": 1}, SMALL, seed=7, species=species)
    r = w.orgs[0]
    assert r.anchor is not None
    anchor0 = r.anchor.copy()
    w.step(1 / 30)
    assert r.state == "free" and w.events[0].kind == "release"
    _run(w, 0.5)
    assert r.state == "free"
    states = []
    for _ in range(20):  # re-anchors at ~1.0 s; the huge release_rate lets go again right after
        w.step(1 / 30)
        states.append(r.state)
    assert "anchored" in states, states
    assert np.linalg.norm(r.anchor - anchor0) > 50  # moved before re-anchoring


def test_debris_rides_the_current_and_the_amoeba_does_not():
    w = World({"debris": 5, "amoeba": 1}, (3000, 2400), seed=1, drift_um_s=100.0)
    start = {o.id: o.pos.copy() for o in w.orgs}
    d0 = w.drift()
    _run(w, 1.0)
    for o in w.orgs:
        moved = o.pos - start[o.id]
        if o.species == "debris":
            assert 80 < np.linalg.norm(moved) < 120, moved
            assert np.dot(moved, d0) / (np.linalg.norm(moved) * np.linalg.norm(d0)) > 0.95
        else:
            assert np.linalg.norm(moved) < 10


def test_paramecium_backs_off_a_wall_instead_of_crossing_it():
    species = load_params('{"paramecium": {"motion": {"turn_sigma": 0, "wobble_amp": 0}}}')
    w = World({"paramecium": 1}, SMALL, seed=2, species=species, drift_um_s=0.0)
    p = w.orgs[0]
    p.pos[:] = (SMALL[0] * 0.5, SMALL[1] * 0.5)
    p.heading = 0.0  # straight at the right wall
    seen_avoid = False
    for _ in range(300):
        w.step(1 / 30)
        seen_avoid |= p.state == "avoid"
        assert p.pos[0] <= SMALL[0]
    assert seen_avoid and p.state == "swim"
    assert abs(math.cos(p.heading)) < 0.99 or math.cos(p.heading) < 0  # not still heading +x


def test_lacrymaria_neck_stays_within_reach():
    w = World({"lacrymaria": 2}, SMALL, seed=9)
    reach = SPECIES["lacrymaria"].motion.neck_reach
    seen_long = False
    for _ in range(300):
        w.step(1 / 30)
        for o in w.orgs:
            assert 0 <= o.neck <= reach
            seen_long |= o.neck > 0.4 * reach
    assert seen_long


def test_daphnia_hops_then_coasts():
    w = World({"daphnia": 1}, (6000, 4800), seed=4)
    d = w.orgs[0]
    speeds = []
    for _ in range(240):
        before = d.pos.copy()
        w.step(1 / 60)
        speeds.append(np.linalg.norm(d.pos - before) * 60)
    speeds = np.array(speeds)
    assert speeds.max() > 4000  # a burst
    assert np.median(speeds) < 600  # mostly coasting


@pytest.mark.parametrize("polarity", ["darkfield", "brightfield"])
def test_render_returns_a_frame_of_the_right_polarity(polarity):
    w = World({"paramecium": 2, "debris": 3}, (960, 720), seed=1)
    img = render(w, (320, 240), 3.0, polarity, np.random.default_rng(0))
    assert img.shape == (240, 320, 3) and img.dtype == np.uint8
    bg = np.median(img[..., 0])
    assert (bg < 40) if polarity == "darkfield" else (bg > 200)
    # NA 0.1 has a 3.4 µm Airy radius: wider than a 3 µm pixel, so thin dark detail
    # washes out in focus (64 -> 102 at this seed). Bodies are still clearly dark.
    assert (img[..., 0].max() > 150) if polarity == "darkfield" else (img[..., 0].min() < 150)


def test_blur_softens_edges_and_rejects_negatives():
    w = World({"paramecium": 2}, (960, 720), seed=1)
    sharp = render(w, (320, 240), 3.0, "darkfield", np.random.default_rng(0), noise=0.0)
    soft = render(w, (320, 240), 3.0, "darkfield", np.random.default_rng(0), noise=0.0, blur_um=20)
    g = lambda im: np.abs(np.diff(im[..., 0].astype(float), axis=1)).max()  # noqa: E731
    assert g(soft) < 0.6 * g(sharp), (g(soft), g(sharp))
    assert soft[..., 0].max() > 100  # still a visible organism
    with pytest.raises(ValueError, match="blur"):
        render(w, (64, 48), 3.0, "darkfield", np.random.default_rng(0), blur_um=-1)


def test_render_rejects_unknown_polarity():
    w = World({"paramecium": 1}, (300, 300), seed=1)
    with pytest.raises(ValueError, match="polarity"):
        render(w, (100, 100), 3.0, "phase", np.random.default_rng(0))


# ---- depth ------------------------------------------------------------------

STRAIGHT = '{"paramecium": {"motion": {"turn_sigma": 0, "wobble_amp": 0}}}'


def _head_on(dz: float) -> tuple[World, Organism, Organism]:
    """Two straight-swimming Paramecia on one line, approaching, ``dz`` µm apart in Z."""
    w = World(
        {"paramecium": 2},
        (3000, 600),
        seed=3,
        species=load_params(STRAIGHT),
        drift_um_s=0.0,
        depth_um=150.0,
        z_walk=0.0,
    )
    a, b = w.orgs
    a.pos[:], a.heading, a.z, a.speed = (600.0, 300.0), 0.0, 75.0 - dz / 2, 1000.0
    b.pos[:], b.heading, b.z, b.speed = (2400.0, 300.0), math.pi, 75.0 + dz / 2, 1000.0
    return w, a, b  # they meet at x=1500 after 0.9 s; 1.5 s keeps both clear of the walls


def test_swimmers_in_different_layers_pass_over_each_other():
    w, a, b = _head_on(dz=100.0)  # thickness ~51 µm each: no contact possible
    states = set()
    for _ in range(45):
        w.step(1 / 30)
        states.update((a.state, b.state))
    assert states == {"swim"}, states
    assert a.pos[0] > b.pos[0] + 500  # crossed and kept going
    assert a.heading == 0.0 and b.heading == math.pi
    assert a.z == pytest.approx(25.0) and b.z == pytest.approx(125.0)  # z_walk 0: fixed


def test_swimmers_in_the_same_layer_still_bump():
    w, a, b = _head_on(dz=10.0)
    seen_avoid = False
    for _ in range(45):
        w.step(1 / 30)
        seen_avoid |= a.state == "avoid" or b.state == "avoid"
    assert seen_avoid
    assert a.heading != 0.0 or b.heading != math.pi  # somebody turned away


def test_flat_world_is_the_old_sim():
    cast = parse_cast(DEFAULT_CAST, SPECIES)
    flat, old = World(cast, (1800, 1400), seed=4, depth_um=0.0), World(cast, (1800, 1400), seed=4)
    for w in (flat, old):
        _run(w, 2)
    assert np.array_equal(np.array([o.pos for o in flat.orgs]), np.array([o.pos for o in old.orgs]))
    assert all(o.z == 0.0 for o in flat.orgs)
    assert all(float(r[8]) == 0.0 for r in flat.truth_rows(3.0))
    deep = World(cast, (1800, 1400), seed=4, depth_um=150.0)
    _run(deep, 2)
    assert all(0.0 <= o.z <= 150.0 for o in deep.orgs)
    assert len({round(o.z, 3) for o in deep.orgs}) > 1


def test_sessile_and_anchored_keep_their_z_and_swimmers_wander():
    w = World({"stentor": 1, "rotifer": 1, "paramecium": 3}, (3000, 2400), seed=5, depth_um=150.0)
    z0 = {o.id: o.z for o in w.orgs}
    _run(w, 2)
    for o in w.orgs:
        if o.species in ("stentor", "rotifer"):
            assert o.z == z0[o.id]
        else:
            assert o.z != z0[o.id] and 0.0 <= o.z <= 150.0


@pytest.mark.parametrize(
    "bad", [dict(depth_um=-1), dict(z_walk=-1), dict(depth_um=100, focus_um=101)]
)
def test_world_rejects_bad_depth(bad):
    with pytest.raises(ValueError):
        World({"paramecium": 1}, SMALL, seed=1, **bad)


def _one_at(z: float, polarity: str = "darkfield") -> np.ndarray:
    w = World({"paramecium": 1}, (900, 900), seed=1, depth_um=150.0, focus_um=75.0)
    o = w.orgs[0]
    o.pos[:], o.z = (450.0, 450.0), z
    return render(w, (300, 300), 3.0, polarity, np.random.default_rng(0), noise=0.0)[..., 0]


def test_out_of_focus_body_is_softer_and_wider():
    # default objective NA 0.10: DoF 55 µm, a 7 µm-radius disc at 70 µm out
    sharp, soft, edge = _one_at(75.0), _one_at(145.0), _one_at(75.0 + 10.0)
    diff = np.abs(sharp.astype(int) - edge.astype(int))
    assert diff.max() <= 12  # inside the depth of field almost nothing changes
    assert soft.max() < sharp.max() - 20
    assert (soft > 20).sum() > 1.015 * (sharp > 20).sum()  # bg is 18 at noise 0; 2 px wider

    def edge(img: np.ndarray) -> float:
        return float(np.abs(np.diff(img.astype(float), axis=1)).max())

    assert edge(soft) < 0.75 * edge(sharp)
    assert sharp.sum() * 0.8 < soft.sum() < sharp.sum() * 1.2  # light is spread, not lost
    bf_sharp, bf_soft = _one_at(75.0, "brightfield"), _one_at(145.0, "brightfield")
    assert bf_soft.min() > bf_sharp.min() + 8  # 113 -> 125: in focus is already Airy-soft


# ---- multi-focal planes -------------------------------------------------------

X10 = Optics(0.25)


def test_plane_focuses_centre_on_focus_and_stay_in_the_chamber():
    w = World({"paramecium": 1}, SMALL, seed=1, depth_um=150.0, focus_um=75.0)
    assert plane_focuses(w, 1, 0.0) == [75.0]
    assert plane_focuses(w, 3, 30.0) == [45.0, 75.0, 105.0]
    assert plane_focuses(w, 4, 20.0) == [45.0, 65.0, 85.0, 105.0]
    for planes, spacing in [(0, 10.0), (3, 0.0), (3, -5.0), (3, 80.0)]:
        with pytest.raises(ValueError):
            plane_focuses(w, planes, spacing)


def _sharpness(img: np.ndarray) -> float:
    import cv2

    return float(cv2.Laplacian(img[..., 0].astype(np.float32), cv2.CV_32F).var())


def _three_at(z: float, **kw) -> list[np.ndarray]:
    w = World({"paramecium": 1}, (240, 240), seed=2, depth_um=150.0, focus_um=75.0)
    o = w.orgs[0]
    o.pos[:], o.z = (120.0, 120.0), z
    kw.setdefault("noise", 0.0)
    return render_planes(
        w,
        (400, 400),
        0.6,
        "darkfield",
        np.random.default_rng(0),
        [45.0, 75.0, 105.0, None],
        X10,
        **kw,
    )


@pytest.mark.parametrize("z, sharpest", [(45.0, 0), (75.0, 1), (105.0, 2), (95.0, 2)])
def test_each_body_is_sharpest_in_the_plane_nearest_it(z, sharpest):
    planes = _three_at(z)[:3]
    s = [_sharpness(p) for p in planes]
    assert int(np.argmax(s)) == sharpest, s


def test_planes_image_the_same_instant_and_the_oracle_is_in_focus():
    """Same body in every plane (sprites drawn once per frame, not per plane), and
    the all-in-focus oracle equals the plane that happens to sit on the body."""
    planes = _three_at(75.0)
    assert np.array_equal(planes[1], planes[3])
    centroids = []
    for p in planes:
        y, x = np.nonzero(p[..., 0] > 30)
        centroids.append((x.mean(), y.mean()))
    assert np.ptp(np.array(centroids), axis=0).max() < 1.0


def test_one_plane_is_render():
    w1 = World({"paramecium": 2, "debris": 3}, SMALL, seed=4, depth_um=150.0)
    w2 = World({"paramecium": 2, "debris": 3}, SMALL, seed=4, depth_um=150.0)
    a = render(w1, (200, 160), 3.0, "darkfield", np.random.default_rng(1))
    (b,) = render_planes(w2, (200, 160), 3.0, "darkfield", np.random.default_rng(1), [w2.focus])
    assert np.array_equal(a, b)


def test_per_plane_noise_and_its_length_is_checked():
    quiet, loud = _three_at(75.0, noise=[0.0, 20.0, 0.0, 0.0])[:2]
    assert quiet[:20, :20, 0].std() == 0 and loud[:20, :20, 0].std() > 10
    with pytest.raises(ValueError):
        _three_at(75.0, noise=[1.0, 2.0])
