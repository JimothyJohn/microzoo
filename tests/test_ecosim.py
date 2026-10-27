"""Behaviour contracts of the ecosystem sim, without video: determinism,
walls, the predator/prey state machine, Stentor's one-frame contraction,
rotifer release, and convection that moves debris but not the anchored."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ecosim import DEFAULT_CAST, World, parse_cast, render
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
    assert (img[..., 0].max() > 150) if polarity == "darkfield" else (img[..., 0].min() < 100)


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
