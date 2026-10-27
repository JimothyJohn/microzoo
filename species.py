#!/usr/bin/env python3
"""species.py: the cast as data. Geometry, motion and look per organism.

Everything the sprite renderer (sprites.py) and the behaviour sim (ecosim.py)
know about an organism lives here, in micrometres and seconds, so the same
numbers can later be *fitted* from real track CSVs (trackstats.py) instead of
typed in. ``python species.py`` dumps the defaults as JSON; ``ecosim.py
--params`` loads an edited copy back.

Numbers come from CLAUDE.md's cheat sheet plus the darkfield references in
references/images.json. Treat them as priors, not measurements.

The cast spans three tiers so a clip can be set at any rung of the food chain:
``microbe`` (bacteria, flagellates, diatoms: 2-60 µm, needs 40x), ``ciliate``
(the 50 µm-2 mm pond cast at 4x-10x) and ``metazoan`` (Daphnia, copepods,
Hydra: 0.3-5 mm, the TOMLOV's range). ``Motion.prey`` names what each one eats
and ``Motion.prey_ratio`` caps the prey's length relative to its own, so the
same hunt code runs a Didinium strike, a Tetrahymena grazing bacteria and a
Hydra pulling in a Daphnia. ``food_web()`` lists the edges.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field, fields, replace

__all__ = [
    "Look",
    "Motion",
    "Species",
    "SPECIES",
    "TIERS",
    "KINDS",
    "food_web",
    "load_params",
    "dump_params",
]

TIERS = ("microbe", "ciliate", "metazoan", "none")
KINDS = (
    "swim",  # cruise, bump, back off
    "hunt",  # cruise, strike prey, swallow, digest
    "sessile",  # foot on a wall, contracts when something passes
    "anchored",  # holds on, lets go, swims, re-anchors
    "neck",  # Lacrymaria: cruise with a searching neck
    "crawl",  # along surfaces; proboscis or legs
    "drift",  # amoeboid creep on the glass
    "hop",  # burst then coast (Daphnia, copepods, Halteria)
    "passive",  # rides the current
    "tumble",  # run-and-tumble (bacteria, flagellates)
    "glide",  # smooth on the glass, no wobble, ignores the current (diatoms, Euplotes)
    "wriggle",  # sinusoidal thrash with slow net progress (nematodes)
    "trap",  # fixed body with a reach that captures what touches it (heliozoa, Hydra)
)


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
    flagellum: int = (
        0  # whip-like flagella trailing from the anterior end (Euglena 1, Chlamydomonas 2)
    )
    eyespot: float = 0.0  # bright stigma near the anterior end (0 = none)
    shell: bool = False  # rigid outline (diatom frustule, ostracod valves, Volvox sphere)
    stalk: bool = False  # Vorticella: bell on a stalk that coils when contracted
    axopodia: bool = False  # Actinosphaerium: stiff rays all round
    worm: bool = False  # nematode: sinusoidal body, phase drives the wave
    tentacles: int = 0  # Hydra: tentacles from the anterior end
    legs: int = 0  # tardigrade: leg pairs
    contractile: bool = False  # body shortens with ``contraction`` (Spirostomum)


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
    prey: tuple[str, ...] = ()  # species this one eats; empty = eats nothing modelled here
    prey_ratio: float = 1.0  # longest prey it takes, as a fraction of its own length
    strike_radius: float = 0.0  # feeders: engage when prey is this close (µm)
    ingest_time: float = 0.0  # feeders: seconds to swallow prey (0 = grazed in one frame)
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
    tumble_rate: float = 0.0  # tumble: direction resets per second
    wriggle_hz: float = 0.0  # wriggle: body wave frequency


@dataclass(frozen=True)
class Species:
    name: str
    role: str
    length_um: float
    aspect: float  # width / length
    motion: Motion
    look: Look
    length_cv: float = 0.15  # per-individual size spread
    thick: float = 0.55  # body thickness / width; bodies only touch when they overlap in Z
    tier: str = "ciliate"  # microbe | ciliate | metazoan | none; which --preset view it belongs to
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
            prey=("bacteria",),
            prey_ratio=0.1,
            strike_radius=15,
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
            prey=("paramecium", "blepharisma", "tetrahymena"),
            prey_ratio=2.2,
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
        motion=Motion(
            kind="sessile",
            contract_radius=200,
            contract_rate=0.03,
            reextend_time=4.0,
            prey=("bacteria", "chlamydomonas", "tetrahymena", "halteria"),
            prey_ratio=0.12,
            strike_radius=120,
        ),
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
            kind="anchored",
            speed=350,
            turn_sigma=1.0,
            release_rate=0.02,
            release_time=2.5,
            prey=("bacteria", "chlamydomonas"),
            prey_ratio=0.1,
            strike_radius=40,
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
        motion=Motion(
            kind="neck",
            speed=60,
            turn_sigma=0.5,
            neck_reach=800,
            neck_hz=0.35,
            prey=("tetrahymena", "halteria", "chlamydomonas", "euglena"),
            prey_ratio=0.8,
            strike_radius=60,
            ingest_time=3.0,
            digest_time=10.0,
            digest_speed=30,
        ),
        look=Look(rim=0.85, interior=0.3, granules=0.4, halo=0.1, neck=True),
        notes="teardrop body, neck whips out to many body lengths in under a second",
        references=("Lacrymaria olor montage-dark.jpg", "Lacrymaria olor - 160x (13465052303).jpg"),
    ),
    "dileptus": Species(
        name="dileptus",
        role="predator",
        length_um=380,
        aspect=0.22,
        motion=Motion(
            kind="crawl",
            speed=220,
            turn_sigma=0.4,
            prey=("paramecium", "tetrahymena", "blepharisma", "halteria", "euglena"),
            prey_ratio=0.8,
            strike_radius=90,
            ingest_time=6.0,
            digest_time=15.0,
            digest_speed=80,
        ),
        look=Look(rim=0.8, interior=0.3, granules=0.5, halo=0.15, proboscis=True, nucleus=0.2),
        notes="slow, trunk sweeps side to side ahead of it",
        references=("Dileptus anatinus - 400x (28675744772).jpg",),
    ),
    "amoeba": Species(
        name="amoeba",
        role="engulfer",
        length_um=260,
        aspect=0.8,
        motion=Motion(
            kind="drift",
            speed=3,
            turn_sigma=0.2,
            prey=("bacteria", "chlamydomonas", "diatom", "tetrahymena", "euglena"),
            prey_ratio=0.3,
            strike_radius=40,
            ingest_time=20.0,
            digest_time=60.0,
            digest_speed=2,
        ),
        look=Look(rim=0.6, interior=0.35, granules=0.7, halo=0.0, blob=True, nucleus=0.25),
        notes="timelapse only; outline creeps",
        references=("Amoeba proteus (Light Microscope).jpg",),
    ),
    "daphnia": Species(
        name="daphnia",
        role="big prey",
        length_um=1500,
        aspect=0.65,
        motion=Motion(
            kind="hop",
            hop_speed=10000,
            hop_time=0.08,
            hop_rate=1.2,
            sink=400,
            prey=("bacteria", "chlamydomonas", "diatom"),
            prey_ratio=0.06,
            strike_radius=200,
        ),
        look=Look(rim=0.8, interior=0.3, granules=0.6, halo=0.0, antennae=True, nucleus=0.3),
        tier="metazoan",
        notes="TOMLOV territory; jumps 10+ mm/s then sinks; filters algae and bacteria",
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
        tier="none",
        notes="rides the convection; the thing the tracker must learn to ignore",
    ),
    # ---- microbe tier: the bottom of the chain, 40x territory ------------------
    "bacteria": Species(
        name="bacteria",
        role="base of the chain",
        length_um=3,
        aspect=0.4,
        length_cv=0.3,
        thick=1.0,
        tier="microbe",
        motion=Motion(kind="tumble", speed=25, speed_cv=0.4, turn_sigma=0.3, tumble_rate=1.0),
        look=Look(rim=0.7, interior=0.4, granules=0.0, halo=0.0),
        notes="rod, run-and-tumble; a point at 4x, the food of everything ciliate-sized",
    ),
    "chlamydomonas": Species(
        name="chlamydomonas",
        role="alga, grazed",
        length_um=12,
        aspect=0.8,
        thick=1.0,
        tier="microbe",
        motion=Motion(kind="tumble", speed=100, speed_cv=0.3, turn_sigma=1.5, tumble_rate=0.5),
        look=Look(rim=0.8, interior=0.5, granules=0.3, halo=0.0, flagellum=2, eyespot=0.6),
        notes="green egg with two flagella, jerky breaststroke, steers to light",
    ),
    "euglena": Species(
        name="euglena",
        role="flagellate, grazed",
        length_um=60,
        aspect=0.2,
        thick=0.9,
        tier="microbe",
        motion=Motion(kind="swim", speed=120, turn_sigma=0.6, wobble_amp=0.5, wobble_hz=1.0),
        look=Look(rim=0.8, interior=0.45, granules=0.5, halo=0.0, flagellum=1, eyespot=0.8),
        notes="spindle with one long flagellum and a red eyespot; corkscrews",
    ),
    "diatom": Species(
        name="diatom",
        role="alga, grazed",
        length_um=60,
        aspect=0.25,
        length_cv=0.4,
        thick=0.3,
        tier="microbe",
        motion=Motion(kind="glide", speed=4, turn_sigma=0.05),
        look=Look(rim=1.0, interior=0.35, granules=0.6, halo=0.0, shell=True),
        notes="glass pillbox, glides along the slide; nearly static to the tracker",
    ),
    "volvox": Species(
        name="volvox",
        role="colonial alga, grazed",
        length_um=400,
        aspect=1.0,
        thick=1.0,
        tier="ciliate",
        motion=Motion(kind="swim", speed=300, turn_sigma=0.3, wobble_amp=0.2, wobble_hz=0.5),
        look=Look(rim=0.9, interior=0.2, granules=0.4, halo=0.15, vacuoles=5, shell=True),
        notes="hollow sphere rolling as it swims; daughter colonies inside",
    ),
    # ---- ciliate tier additions --------------------------------------------------
    "tetrahymena": Species(
        name="tetrahymena",
        role="bacterivore, prey",
        length_um=50,
        aspect=0.55,
        thick=0.7,
        motion=Motion(
            kind="swim",
            speed=450,
            turn_sigma=1.2,
            wobble_amp=0.3,
            wobble_hz=2.0,
            avoid_time=0.15,
            prey=("bacteria",),
            prey_ratio=0.15,
            strike_radius=8,
        ),
        look=Look(rim=0.85, interior=0.3, granules=0.5, halo=0.2, vacuoles=3),
        notes="small pear-shaped Paramecium relative; the standard lab bacterivore",
    ),
    "halteria": Species(
        name="halteria",
        role="bacterivore, prey",
        length_um=30,
        aspect=0.9,
        thick=0.9,
        motion=Motion(
            kind="hop",
            speed=80,
            hop_speed=3000,
            hop_time=0.03,
            hop_rate=1.5,
            prey=("bacteria",),
            prey_ratio=0.15,
            strike_radius=6,
        ),
        look=Look(rim=0.85, interior=0.3, granules=0.4, halo=0.35),
        notes="the jumping ciliate: sits, then vanishes 10 body lengths away in one frame",
    ),
    "coleps": Species(
        name="coleps",
        role="predator / scavenger",
        length_um=60,
        aspect=0.5,
        thick=0.9,
        motion=Motion(
            kind="hunt",
            speed=400,
            turn_sigma=1.4,
            prey=("tetrahymena", "halteria", "chlamydomonas", "euglena"),
            prey_ratio=1.2,
            strike_radius=25,
            ingest_time=3.0,
            digest_time=8.0,
            digest_speed=100,
        ),
        look=Look(rim=0.95, interior=0.35, granules=0.3, halo=0.1, belts=2, shell=True),
        notes="armoured barrel; swarms on anything wounded, takes small swimmers whole",
    ),
    "euplotes": Species(
        name="euplotes",
        role="bacterivore, crawler",
        length_um=100,
        aspect=0.6,
        thick=0.3,
        motion=Motion(
            kind="glide",
            speed=150,
            turn_sigma=2.5,
            prey=("bacteria", "chlamydomonas"),
            prey_ratio=0.15,
            strike_radius=15,
        ),
        look=Look(rim=0.85, interior=0.3, granules=0.5, halo=0.3, nucleus=0.3),
        notes="flat oval walking on cirri; stop-start darts over the glass",
    ),
    "blepharisma": Species(
        name="blepharisma",
        role="prey/grazer",
        length_um=150,
        aspect=0.35,
        motion=Motion(
            kind="swim",
            speed=300,
            turn_sigma=0.6,
            wobble_amp=0.2,
            wobble_hz=1.0,
            prey=("bacteria", "chlamydomonas", "tetrahymena"),
            prey_ratio=0.35,
            strike_radius=20,
        ),
        look=Look(rim=0.8, interior=0.35, granules=0.6, halo=0.2, vacuoles=4, nucleus=0.3),
        notes="pink, slower than Paramecium, same slipper; Didinium takes it too",
    ),
    "vorticella": Species(
        name="vorticella",
        role="sessile bacterivore",
        length_um=300,
        aspect=0.2,
        thick=1.0,
        motion=Motion(
            kind="sessile",
            contract_radius=80,
            contract_rate=0.05,
            reextend_time=3.0,
            prey=("bacteria", "chlamydomonas"),
            prey_ratio=0.06,
            strike_radius=50,
        ),
        look=Look(rim=0.85, interior=0.3, granules=0.4, halo=0.3, stalk=True, nucleus=0.0),
        notes="bell on a 250 µm stalk; the stalk coils in a few ms, re-extends over seconds",
    ),
    "spirostomum": Species(
        name="spirostomum",
        role="giant grazer",
        length_um=1500,
        aspect=0.08,
        thick=1.0,
        motion=Motion(
            kind="swim",
            speed=400,
            turn_sigma=0.3,
            avoid_time=0.2,
            avoid_turn=0.6,
            contract_radius=1,
            reextend_time=2.5,
            prey=("bacteria", "chlamydomonas"),
            prey_ratio=0.02,
            strike_radius=40,
        ),
        look=Look(rim=0.8, interior=0.3, granules=0.6, halo=0.15, nucleus=0.0, contractile=True),
        notes="a worm-like ciliate up to 3 mm; snaps to a quarter length when touched",
    ),
    "actinosphaerium": Species(
        name="actinosphaerium",
        role="sessile predator",
        length_um=300,
        aspect=1.0,
        thick=1.0,
        motion=Motion(
            kind="trap",
            prey=(
                "paramecium",
                "blepharisma",
                "tetrahymena",
                "halteria",
                "euglena",
                "chlamydomonas",
                "rotifer",
            ),
            prey_ratio=1.0,
            strike_radius=260,
            ingest_time=25.0,
            digest_time=90.0,
        ),
        look=Look(rim=0.7, interior=0.3, granules=0.8, halo=0.0, axopodia=True, vacuoles=8),
        notes="heliozoan sun: a ball of vacuoles with stiff rays; whatever swims into them sticks",
    ),
    # ---- metazoan tier: the TOMLOV's range ---------------------------------------
    "cyclops": Species(
        name="cyclops",
        role="predator (copepod)",
        length_um=1000,
        aspect=0.35,
        thick=0.8,
        tier="metazoan",
        motion=Motion(
            kind="hop",
            speed=200,
            hop_speed=20000,
            hop_time=0.03,
            hop_rate=0.8,
            sink=150,
            prey=("rotifer", "paramecium", "blepharisma", "tetrahymena", "halteria", "euglena"),
            prey_ratio=0.5,
            strike_radius=150,
            ingest_time=5.0,
            digest_time=20.0,
        ),
        look=Look(rim=0.85, interior=0.35, granules=0.5, halo=0.0, antennae=True, nucleus=0.0),
        notes="teardrop with long antennae, hops in jerks, grabs rotifers and ciliates",
    ),
    "ostracod": Species(
        name="ostracod",
        role="grazer (seed shrimp)",
        length_um=700,
        aspect=0.6,
        thick=0.8,
        tier="metazoan",
        motion=Motion(
            kind="swim",
            speed=2000,
            turn_sigma=0.8,
            avoid_time=0.2,
            prey=("bacteria", "chlamydomonas", "diatom"),
            prey_ratio=0.1,
            strike_radius=100,
        ),
        look=Look(rim=1.0, interior=0.25, granules=0.3, halo=0.0, shell=True, nucleus=0.0),
        notes="bean in two valves, steady smooth swimmer; the shell hides everything inside",
    ),
    "nematode": Species(
        name="nematode",
        role="grazer (roundworm)",
        length_um=800,
        aspect=0.05,
        thick=1.0,
        tier="metazoan",
        motion=Motion(
            kind="wriggle",
            speed=150,
            turn_sigma=0.8,
            wriggle_hz=2.0,
            prey=("bacteria",),
            prey_ratio=0.01,
            strike_radius=30,
        ),
        look=Look(rim=0.8, interior=0.3, granules=0.3, halo=0.0, worm=True),
        notes="thrashes in S-curves, slow net progress; Hydra and planarians take it",
    ),
    "tardigrade": Species(
        name="tardigrade",
        role="grazer (water bear)",
        length_um=350,
        aspect=0.4,
        thick=0.8,
        tier="metazoan",
        motion=Motion(
            kind="crawl",
            speed=40,
            turn_sigma=0.5,
            prey=("chlamydomonas", "diatom", "rotifer"),
            prey_ratio=0.5,
            strike_radius=60,
            ingest_time=8.0,
            digest_time=30.0,
            digest_speed=20,
        ),
        look=Look(rim=0.8, interior=0.35, granules=0.5, halo=0.0, legs=4, nucleus=0.0),
        notes="eight stubby legs, clambers over debris; sucks algae, takes small rotifers",
    ),
    "gastrotrich": Species(
        name="gastrotrich",
        role="bacterivore",
        length_um=150,
        aspect=0.25,
        thick=0.5,
        tier="metazoan",
        motion=Motion(
            kind="glide",
            speed=200,
            turn_sigma=1.0,
            prey=("bacteria",),
            prey_ratio=0.05,
            strike_radius=20,
        ),
        look=Look(rim=0.8, interior=0.3, granules=0.5, halo=0.2, nucleus=0.0),
        notes="bowling-pin glider with a forked tail, skates over the glass",
    ),
    "hydra": Species(
        name="hydra",
        role="top predator",
        length_um=2500,
        aspect=0.12,
        thick=1.0,
        tier="metazoan",
        motion=Motion(
            kind="trap",
            prey=("daphnia", "cyclops", "ostracod", "nematode", "rotifer"),
            prey_ratio=1.0,
            strike_radius=2000,
            ingest_time=30.0,
            digest_time=600.0,
        ),
        look=Look(rim=0.8, interior=0.35, granules=0.4, halo=0.0, tentacles=6, nucleus=0.0),
        notes="column on the wall, tentacles as long again; stings and swallows Daphnia whole",
    ),
    "planaria": Species(
        name="planaria",
        role="predator (flatworm)",
        length_um=3000,
        aspect=0.2,
        thick=0.3,
        tier="metazoan",
        motion=Motion(
            kind="glide",
            speed=500,
            turn_sigma=0.3,
            prey=("nematode", "tardigrade", "rotifer", "ostracod"),
            prey_ratio=0.4,
            strike_radius=300,
            ingest_time=15.0,
            digest_time=120.0,
        ),
        look=Look(rim=0.7, interior=0.4, granules=0.5, halo=0.0, eyespot=0.5, nucleus=0.0),
        notes="arrow-headed ribbon gliding on cilia; the slide's largest hunter",
    ),
}


def food_web(species: dict[str, Species] = SPECIES) -> list[tuple[str, str]]:
    """Directed (predator, prey) edges for every prey name that exists in ``species``."""
    return [
        (name, prey) for name, sp in species.items() for prey in sp.motion.prey if prey in species
    ]


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
        elif isinstance(cur, tuple):
            if not isinstance(v, (list, tuple)):
                raise ValueError(f"{k!r} must be a list")
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
