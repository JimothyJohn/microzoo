"""species.py is data with a contract: every entry is complete, the JSON dump
round-trips, and partial overrides change exactly what they name."""

from __future__ import annotations

import json

import pytest

from species import SPECIES, Motion, Species, dump_params, load_params

KINDS = {"swim", "hunt", "sessile", "anchored", "neck", "crawl", "drift", "hop", "passive"}


def test_every_species_is_well_formed():
    for name, sp in SPECIES.items():
        assert isinstance(sp, Species) and sp.name == name
        assert sp.length_um > 0 and 0 < sp.aspect <= 1
        assert sp.motion.kind in KINDS, (name, sp.motion.kind)
        assert 0 <= sp.look.rim <= 1 and 0 <= sp.look.interior <= 1


def test_dump_round_trips_through_load():
    text = dump_params()
    again = load_params(text)
    assert again == SPECIES
    assert json.loads(text)["paramecium"]["motion"]["speed"] == SPECIES["paramecium"].motion.speed


def test_partial_override_changes_one_number_only():
    out = load_params('{"paramecium": {"motion": {"speed": 800}}}')
    assert out["paramecium"].motion.speed == 800
    assert out["paramecium"].motion.turn_sigma == SPECIES["paramecium"].motion.turn_sigma
    assert out["paramecium"].look == SPECIES["paramecium"].look
    assert out["didinium"] == SPECIES["didinium"]
    assert SPECIES["paramecium"].motion.speed == 1000  # the base table is untouched


@pytest.mark.parametrize(
    "text",
    [
        '{"unicorn": {}}',
        '{"paramecium": {"motion": {"warp": 9}}}',
        '{"paramecium": {"nope": 1}}',
        '{"paramecium": 3}',
        "[1, 2]",
    ],
)
def test_bad_overrides_are_rejected(text):
    with pytest.raises(ValueError):
        load_params(text)


def test_malformed_json_raises():
    with pytest.raises(ValueError):  # json.JSONDecodeError is a ValueError
        load_params("{not json")


def test_motion_defaults_are_inert():
    m = Motion()
    assert m.speed == 0 and m.strike_radius == 0 and m.hop_speed == 0
