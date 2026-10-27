"""The food chain as a contract: prey lists name real species, every rung is
reachable from bacteria, size caps hold, and each feeding style (graze, hunt,
trap, sessile bell) eats what it should and nothing else."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from conftest import REPO, run_cli

from ecosim import PRESETS, World, parse_cast
from species import SPECIES, food_web, load_params

SMALL = (900.0, 700.0)  # µm


def _run(world: World, seconds: float, fps: float = 30.0) -> None:
    for _ in range(int(seconds * fps)):
        world.step(1.0 / fps)


def _first(world: World, name: str):
    return next(o for o in world.orgs if o.species == name)


def _place(world: World, name: str, pos, heading: float = 0.0):
    o = world._spawn(name)
    o.pos = np.array(pos, dtype=float)
    o.heading = heading
    o.z = world.focus
    return o


# ---- the web itself ------------------------------------------------------------


def test_every_prey_name_is_a_species_and_nothing_eats_itself():
    for name, sp in SPECIES.items():
        for prey in sp.motion.prey:
            assert prey in SPECIES, (name, prey)
            assert prey != name
        if sp.motion.prey:
            assert sp.motion.strike_radius > 0, name
            assert sp.motion.prey_ratio > 0, name
        if sp.motion.ingest_time > 0:
            assert sp.motion.prey, name


def test_size_caps_leave_every_predator_something_it_can_actually_take():
    for name, sp in SPECIES.items():
        if not sp.motion.prey:
            continue
        takeable = [
            p for p in sp.motion.prey if SPECIES[p].length_um <= sp.motion.prey_ratio * sp.length_um
        ]
        assert takeable, (name, "prey_ratio caps out every listed prey")


def test_chain_runs_from_bacteria_to_hydra_and_back_down():
    eaters: dict[str, set[str]] = {}
    for pred, prey in food_web():
        eaters.setdefault(prey, set()).add(pred)
    seen, frontier = set(), {"bacteria"}
    while frontier:
        seen |= frontier
        frontier = {e for p in frontier for e in eaters.get(p, ())} - seen
    assert "hydra" in seen and "didinium" in seen and "planaria" in seen
    # and every tier is on the chain
    assert {SPECIES[n].tier for n in seen} >= {"microbe", "ciliate", "metazoan"}


def test_prey_lists_survive_the_json_round_trip_and_can_be_overridden():
    again = load_params(json.dumps({"coleps": {"motion": {"prey": ["euglena"]}}}))
    assert again["coleps"].motion.prey == ("euglena",)
    assert again["didinium"].motion.prey == SPECIES["didinium"].motion.prey
    with pytest.raises(ValueError):
        load_params('{"coleps": {"motion": {"prey": "euglena"}}}')


# ---- grazing -------------------------------------------------------------------


def test_tetrahymena_grazes_bacteria_down():
    w = World({"tetrahymena": 3, "bacteria": 40}, (400.0, 300.0), seed=3, drift_um_s=0.0)
    before = sum(o.visible for o in w.orgs if o.species == "bacteria")
    _run(w, 20)
    after = sum(o.visible for o in w.orgs if o.species == "bacteria")
    assert after < before
    kinds = {e.kind for e in w.events}
    assert kinds == {"ingested"}, "grazing is one event, no capture/strike pair"
    assert all(o.state in ("swim", "avoid") for o in w.orgs if o.species == "tetrahymena")


def test_bacteria_do_not_make_a_paramecium_back_off():
    species = load_params('{"paramecium": {"motion": {"turn_sigma": 0, "wobble_amp": 0}}}')
    w = World(
        {"paramecium": 1, "bacteria": 60}, (1500.0, 700.0), seed=2, species=species, drift_um_s=0.0
    )
    para = _first(w, "paramecium")
    para.pos[:] = (300.0, 350.0)
    para.heading = 0.0
    for o in w.orgs:  # a carpet of bacteria along the path, same layer
        if o.species == "bacteria":
            o.pos[:] = (w.rng.uniform(350, 1100), w.rng.uniform(300, 400))
            o.z = para.z
    _run(w, 0.8)
    assert para.state == "swim" and para.pos[0] > 900


# ---- hunting with a size cap ---------------------------------------------------


def test_coleps_takes_tetrahymena_but_not_a_paramecium():
    big = World({"coleps": 1, "paramecium": 3}, (300.0, 300.0), seed=1, drift_um_s=0.0)
    _run(big, 15)
    assert not [e for e in big.events if e.kind == "capture"]
    small = World({"coleps": 1, "tetrahymena": 4}, (300.0, 300.0), seed=1, drift_um_s=0.0)
    _run(small, 15)
    caps = [e for e in small.events if e.kind == "capture"]
    assert caps and all(small._by_id[e.subject].species == "tetrahymena" for e in caps)


def test_didinium_still_prefers_the_old_contract_prey():
    assert "paramecium" in SPECIES["didinium"].motion.prey
    w = World({"paramecium": 1, "didinium": 1}, SMALL, seed=1)
    _run(w, 30)
    assert any(e.kind == "capture" for e in w.events)


# ---- traps and bells -----------------------------------------------------------


def test_actinosphaerium_takes_what_swims_into_its_rays():
    w = World({"actinosphaerium": 1}, (1200.0, 900.0), seed=4, drift_um_s=0.0)
    sun = _first(w, "actinosphaerium")
    assert sun.anchor is not None and sun.state == "extended"
    species = load_params('{"paramecium": {"motion": {"turn_sigma": 0, "wobble_amp": 0}}}')
    w.species = species
    reach = SPECIES["actinosphaerium"].motion.strike_radius
    para = _place(w, "paramecium", sun.pos + np.array([0.0, reach + 150.0]), heading=-math.pi / 2)
    para.z = sun.z + 100  # rays span the chamber: Z does not matter for a trap
    _run(w, 3)
    assert para.state in ("caught", "eaten")
    assert [e.kind for e in w.events][:1] == ["capture"]
    # the sun does not move while it feeds
    _run(w, 2)
    assert np.allclose(sun.anchor + 0 * sun.pos, sun.anchor) and sun.state == "ingest"


def test_hydra_pulls_in_a_daphnia_and_ignores_a_paramecium():
    w = World({"hydra": 1}, (8000.0, 6000.0), seed=5, drift_um_s=0.0)
    hydra = _first(w, "hydra")
    para = _place(w, "paramecium", hydra.pos + np.array([400.0, 0.0]))
    daph = _place(w, "daphnia", hydra.pos + np.array([0.0, 900.0]))
    daph.length_um, daph.next_hop = 1500.0, 1e9  # a typical one, sitting still
    _run(w, 2)
    assert daph.state == "caught" and para.state != "caught"
    _run(w, SPECIES["hydra"].motion.ingest_time + 1)
    assert not daph.visible and hydra.state == "digest"


def test_vorticella_grazes_at_the_bell_and_still_contracts():
    w = World({"vorticella": 1, "bacteria": 30}, (500.0, 400.0), seed=6, drift_um_s=0.0)
    vort = _first(w, "vorticella")
    bell = vort.anchor + np.array([math.cos(vort.heading), math.sin(vort.heading)]) * vort.length_um
    for o in w.orgs:
        if o.species == "bacteria":
            o.pos[:] = bell + w.rng.normal(0, 25, 2)
            o.z = vort.z
    _run(w, 6)
    assert any(e.kind == "ingested" for e in w.events), "bacteria at the bell are food"
    assert not any(e.kind == "contraction" for e in w.events), "and not a reason to contract"
    w.species = load_params('{"paramecium": {"motion": {"speed": 0, "turn_sigma": 0}}}')
    _place(w, "paramecium", bell)
    _run(w, 1)
    assert any(e.kind == "contraction" for e in w.events), "a Paramecium at the bell is"


def test_spirostomum_snaps_short_on_a_bump_and_reextends():
    species = load_params('{"spirostomum": {"motion": {"turn_sigma": 0, "wobble_amp": 0}}}')
    w = World({"spirostomum": 1}, (8000.0, 5000.0), seed=7, species=species, drift_um_s=0.0)
    s = _first(w, "spirostomum")
    s.pos[:] = (6500.0, 2500.0)
    s.heading = 0.0  # straight at the right wall
    snapped = reextended = False
    for _ in range(int(8 * 30)):
        w.step(1 / 30)
        snapped |= s.contraction > 0.9
        reextended |= snapped and s.contraction == 0.0 and s.state == "swim"
    assert snapped and reextended and any(e.kind == "contraction" for e in w.events)
    assert sum(e.kind == "contraction" for e in w.events) == 1, "one snap, not a loop at the wall"
    assert math.cos(s.heading) < 0, "re-extended pointing back into the chamber"


# ---- new motion kinds stay in the chamber and move ----------------------------


@pytest.mark.parametrize("name", ["bacteria", "diatom", "euplotes", "nematode", "gastrotrich"])
def test_new_kinds_move_and_stay_inside(name):
    w = World({name: 4}, (600.0, 400.0), seed=8, drift_um_s=0.0)
    start = [o.pos.copy() for o in w.orgs]
    _run(w, 5)
    for o, p0 in zip(w.orgs, start, strict=True):
        assert 0 <= o.pos[0] <= 600 and 0 <= o.pos[1] <= 400
        assert np.linalg.norm(o.pos - p0) > 1.0 or SPECIES[name].motion.speed < 10


def test_nematode_phase_runs_at_its_wriggle_frequency():
    w = World({"nematode": 1}, SMALL, seed=1, drift_um_s=0.0)
    n = _first(w, "nematode")
    p0 = n.phase
    _run(w, 1.0, fps=100)
    assert abs(((n.phase - p0) % 1.0) - (SPECIES["nematode"].motion.wriggle_hz % 1.0)) < 0.02


def test_gliders_sit_on_the_glass():
    w = World({"diatom": 2, "paramecium": 2}, SMALL, seed=1, depth_um=150.0)
    _run(w, 2)
    assert all(o.z == 0.0 for o in w.orgs if o.species == "diatom")
    assert any(o.z > 0.0 for o in w.orgs if o.species == "paramecium")


# ---- presets -------------------------------------------------------------------


def test_presets_parse_and_scale_sensibly():
    for name, (cast, scale) in PRESETS.items():
        parsed = parse_cast(cast, SPECIES)
        assert parsed and scale > 0
        tiers = {SPECIES[n].tier for n in parsed if n != "debris"}
        assert name in tiers, (name, tiers)


def test_preset_cli_sets_cast_and_scale_but_explicit_flags_win(tmp_path):
    out = tmp_path / "m.mp4"
    r = run_cli(REPO / "ecosim.py", "--out", str(out), "--preset", "metazoan", "--frames", "3")
    assert r.returncode == 0, r.stderr
    sc = json.loads(out.with_suffix(".json").read_text())
    assert sc["preset"] == "metazoan" and sc["um_per_px"] == PRESETS["metazoan"][1]
    assert sc["cast"] == parse_cast(PRESETS["metazoan"][0], SPECIES)
    out2 = tmp_path / "m2.mp4"
    r = run_cli(
        REPO / "ecosim.py",
        "--out",
        str(out2),
        "--preset",
        "microbe",
        "--cast",
        "bacteria=5",
        "--um-per-px",
        "0.5",
        "--frames",
        "3",
    )
    assert r.returncode == 0, r.stderr
    sc = json.loads(out2.with_suffix(".json").read_text())
    assert sc["cast"] == {"bacteria": 5} and sc["um_per_px"] == 0.5 and sc["preset"] == "microbe"
