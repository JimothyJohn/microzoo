#!/usr/bin/env python3
"""species.py: the cast as data. Geometry, motion and look per organism.

Everything the sprite renderer (sprites.py) and the behaviour sim (ecosim.py)
know about an organism lives here, in micrometres and seconds, so the same
numbers can later be *fitted* from real track CSVs (trackstats.py) instead of
typed in. ``python species.py`` dumps the defaults as JSON; ``ecosim.py
--params`` loads an edited copy back.

Numbers come from CLAUDE.md's cheat sheet plus the darkfield references in
references/images.json. Treat them as priors, not measurements.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field, fields, replace

__all__ = ["Look", "Motion", "Species", "SPECIES", "load_params", "dump_params"]


@dataclass(frozen=True)
class Look:
    """How the organism renders. Weights are per-feature signal strengths in
    [0, 1]; polarity-specific scaling happens in sprites.py."""

    rim: float = 0.9  # bright pellicle edge under darkfield, dark line under brightfield
    interior: float = 0.3  # translucent body fill
    granules: float = 0.5  # speckle amplitude inside the body
    halo: float = 0.15  # cilia fuzz just outside the rim (0 = none)
    vacuoles: int = 0  # bright/pale food vacuoles
    nucleus: float = 0.0  # one darker macronucleus region (0 = none)
    belts: int = 0  # Didinium's ciliary girdles
    corona: bool = False  # rotifer wheel organs (pulsing)
    trumpet: bool = False  # Stentor
    neck: bool = False  # Lacrymaria
    proboscis: bool = False  # Dileptus
    antennae: bool = False  # Daphnia
    blob: bool = False  # amoeba-style deforming outline


@dataclass(frozen=True)
class Motion:
    """Behaviour parameters. All speeds µm/s, times s, angles rad."""

    kind: str = "swim"  # swim | hunt | sessile | anchored | neck | crawl | hop | drift
    speed: float = 0.0
    speed_cv: float = 0.25  # per-individual spread (coefficient of variation)
    turn_sigma: float = 0.8  # heading random walk, rad / sqrt(s)
    wobble_amp: float = 0.0  # helical/spiral path seen from above: heading wobble amplitude
    wobble_hz: float = 0.0
    avoid_time: float = 0.3  # avoiding reaction: reverse for this long on contact
    avoid_turn: float = 1.2  # then turn by about this much
    strike_radius: float = 0.0  # hunters: engage when prey is this close (µm)
    ingest_time: float = 0.0  # hunters: seconds to swallow prey
    digest_time: float = 0.0  # hunters: slow period after a meal
    digest_speed: float = 0.0
    contract_radius: float = 0.0  # sessile: contract when a swimmer passes this close
    contract_rate: float = 0.0  # sessile: spontaneous contractions per second
    reextend_time: float = 0.0  # sessile: seconds to re-extend
    release_rate: float = 0.0  # anchored: probability per second of letting go
    release_time: float = 0.0  # anchored: seconds free-swimming before re-anchoring
    neck_reach: float = 0.0  # Lacrymaria: max neck length (µm)
    neck_hz: float = 0.0  # Lacrymaria: search sweep frequency
    hop_speed: float = 0.0  # Daphnia: burst speed
    hop_time: float = 0.0  # Daphnia: burst duration
    hop_rate: float = 0.0  # Daphnia: hops per second
    sink: float = 0.0  # Daphnia: passive sink speed between hops


@dataclass(frozen=True)
class Species:
    name: str
    role: str
    length_um: float
    aspect: float  # width / length
    motion: Motion
    look: Look
    length_cv: float = 0.15  # per-individual size spread
    notes: str = ""
    references: tuple[str, ...] = field(default_factory=tuple)  # titles in references/images.json


SPECIES: dict[str, Species] = {
    "paramecium": Species(
        name="paramecium",
        role="prey/grazer",
        length_um=220,
        aspect=0.42,
        motion=Motion(
            kind="swim",
            speed=1000,
            turn_sigma=0.7,
            wobble_amp=0.3,
            wobble_hz=1.6,
            avoid_time=0.25,
            avoid_turn=1.3,
        ),
        look=Look(rim=0.9, interior=0.3, granules=0.6, halo=0.2, vacuoles=6, nucleus=0.35),
        notes="slipper, spirals as it swims, backs up and turns when it bumps something",
        references=(
            "Paramecium & Litonotus - 160x - Dunkelfeld (8491593271).jpg",
            "Paramecium (8423525940).jpg",
            "Paramecium caudatum (250 20) Cultured.jpg",
        ),
    ),
    "didinium": Species(
        name="didinium",
        role="predator of Paramecium",
        length_um=140,
        aspect=0.72,
        motion=Motion(
            kind="hunt",
            speed=1600,
            turn_sigma=1.6,
            strike_radius=70,
            ingest_time=4.0,
            digest_time=12.0,
            digest_speed=250,
        ),
        look=Look(rim=0.85, interior=0.35, granules=0.4, halo=0.1, belts=2, nucleus=0.2),
        notes="barrel with two ciliary girdles and a snout; fast, erratic, strikes on contact",
        references=("Didinium nasutum consuming a paramecium.jpg", "Didinium nasutum 3D-model.jpg"),
    ),
    "stentor": Species(
        name="stentor",
        role="sessile filter feeder",
        length_um=900,
        aspect=0.3,
        motion=Motion(kind="sessile", contract_radius=200, contract_rate=0.03, reextend_time=4.0),
        look=Look(rim=0.8, interior=0.25, granules=0.5, halo=0.25, trumpet=True, nucleus=0.3),
        notes="trumpet anchored to debris; contracts to a ball in ~10 ms (one frame at 60 fps)",
        references=(
            "Stentor coeruleus extended.jpg",
            "Инфузория Stentor coeruleus, темное поле.webm",
        ),
    ),
    "rotifer": Species(
        name="rotifer",
        role="filter feeder",
        length_um=320,
        aspect=0.3,
        motion=Motion(
            kind="anchored", speed=350, turn_sigma=1.0, release_rate=0.02, release_time=2.5
        ),
        look=Look(rim=0.7, interior=0.3, granules=0.5, halo=0.1, corona=True, nucleus=0.0),
        notes="bdelloid: spindle anchored by its foot, corona 'wheels' flicker at ~10 Hz",
        references=(
            "Rotifera - 160x - Dunkelfeld - Formalin (8492706926).jpg",
            "Rotifera (Genusː Philodina) - 40X view.jpg",
        ),
    ),
    "lacrymaria": Species(
        name="lacrymaria",
        role="predator",
        length_um=110,
        aspect=0.45,
        motion=Motion(kind="neck", speed=60, turn_sigma=0.5, neck_reach=800, neck_hz=0.35),
        look=Look(rim=0.85, interior=0.3, granules=0.4, halo=0.1, neck=True),
        notes="teardrop body, neck whips out to many body lengths in under a second",
        references=("Lacrymaria olor montage-dark.jpg", "Lacrymaria olor - 160x (13465052303).jpg"),
    ),
    "dileptus": Species(
        name="dileptus",
        role="predator",
        length_um=380,
        aspect=0.22,
        motion=Motion(kind="crawl", speed=220, turn_sigma=0.4),
        look=Look(rim=0.8, interior=0.3, granules=0.5, halo=0.15, proboscis=True, nucleus=0.2),
        notes="slow, trunk sweeps side to side ahead of it",
        references=("Dileptus anatinus - 400x (28675744772).jpg",),
    ),
    "amoeba": Species(
        name="amoeba",
        role="engulfer",
        length_um=260,
        aspect=0.8,
        motion=Motion(kind="drift", speed=3, turn_sigma=0.2),
        look=Look(rim=0.6, interior=0.35, granules=0.7, halo=0.0, blob=True, nucleus=0.25),
        notes="timelapse only; outline creeps",
        references=("Amoeba proteus (Light Microscope).jpg",),
    ),
    "daphnia": Species(
        name="daphnia",
        role="big prey",
        length_um=1500,
        aspect=0.65,
        motion=Motion(kind="hop", hop_speed=10000, hop_time=0.08, hop_rate=1.2, sink=400),
        look=Look(rim=0.8, interior=0.3, granules=0.6, halo=0.0, antennae=True, nucleus=0.3),
        notes="TOMLOV territory; jumps 10+ mm/s then sinks",
        references=(
            "Daphnia pulex (Water Flea) specimens, Chapeltoun, East Ayrshire.jpg",
            "Freshwater copepod (Copepoda) under darkfield microscopy.jpg",
        ),
    ),
    "debris": Species(
        name="debris",
        role="not alive",
        length_um=25,
        aspect=0.7,
        length_cv=0.6,
        motion=Motion(kind="passive"),
        look=Look(rim=0.5, interior=0.5, granules=0.3, halo=0.0, blob=True),
        notes="rides the convection; the thing the tracker must learn to ignore",
    ),
}


def dump_params(species: dict[str, Species] = SPECIES) -> str:
    return json.dumps({k: asdict(v) for k, v in species.items()}, indent=2)


def _merge(obj, overrides: dict):
    """Rebuild a frozen dataclass with ``overrides`` applied (nested dicts recurse)."""
    kw = {}
    names = {f.name for f in fields(obj)}
    for k, v in overrides.items():
        if k not in names:
            raise ValueError(f"unknown field {k!r} for {type(obj).__name__}")
        cur = getattr(obj, k)
        if isinstance(v, dict) and hasattr(cur, "__dataclass_fields__"):
            kw[k] = _merge(cur, v)
        elif k == "references":
            kw[k] = tuple(v)
        else:
            kw[k] = v
    return replace(obj, **kw)


def load_params(text: str, base: dict[str, Species] = SPECIES) -> dict[str, Species]:
    """Species table with a JSON override applied. The JSON may be partial:
    ``{"paramecium": {"motion": {"speed": 800}}}`` changes one number."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("params JSON must be an object keyed by species name")
    out = dict(base)
    for name, over in data.items():
        if name not in out:
            raise ValueError(f"unknown species {name!r}; known: {sorted(out)}")
        if not isinstance(over, dict):
            raise ValueError(f"{name}: expected an object")
        out[name] = _merge(out[name], over)
    return out


if __name__ == "__main__":
    sys.stdout.write(dump_params() + "\n")
