#!/usr/bin/env python3
"""ecosim.py: an agent-based drop of pond water, rendered through sprites.py.

Every organism in species.py gets a behaviour: Paramecium spiral, bump and
back off; Didinium hunt, strike, swallow and digest; Stentor sit on the wall
and snap shut when something passes; rotifers hold on and let go; Lacrymaria
whip a neck out; Dileptus sweep a trunk; Daphnia hop; debris rides a slow
rotating convection current that every free swimmer also feels. The whole
thing is deterministic for a seed and writes what track.py needs to be judged
against, plus the events a future v3 detector should find:

    <out>                 the clip (mp4v)
    <stem>_truth.csv      frame, obj_id, x, y, species, state, heading, length_px, z_um
    <stem>_events.csv     frame, t, kind, actor, subject, x, y  (capture, ingested,
                          contraction, release)
    <stem>.json           sidecar: the parameters that produced the clip; track.py
                          embeds it, so a tracked clip carries its own model.

    python ecosim.py --out data/eco.mp4 --frames 600 --fps 30 --size 960x720 \\
        --um-per-px 3 --cast paramecium=8,didinium=2,stentor=1,rotifer=2,debris=30

The chamber has depth (``--depth``, µm): every free swimmer carries a Z, bodies
only bump when they overlap in Z, so most crossings are pass-overs, and anything
outside the depth of field (``--dof`` around ``--focus``) renders with a mild
defocus blur. ``--depth 0`` is the old flat sim.

``--params my.json`` overrides any number in species.py (see ``--dump-params``);
that file is the thing trackstats.py should one day fill in from real footage.
Units inside the sim are micrometres and seconds; pixels only at the edges.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling modules under python -I
from species import SPECIES, Species, dump_params, load_params  # noqa: E402
from sprites import (  # noqa: E402
    POLARITIES,
    SpriteState,
    composite,
    render_sprite,
    stentor_length,
)

__all__ = ["DEFAULT_CAST", "Event", "Organism", "World", "parse_cast", "render", "write_clip"]

DEFAULT_CAST = "paramecium=8,didinium=2,stentor=1,rotifer=2,lacrymaria=1,dileptus=1,debris=30"
EVENT_KINDS = ("capture", "ingested", "contraction", "release")
Z_WALK_UM_SQRT_S = 20.0  # free swimmers' Z random walk, µm / sqrt(s)
DEFOCUS_SIGMA_UM_PER_UM = 0.1  # blur sigma (µm) per µm outside the depth of field, ~NA at 4x
_Z_WALKERS = frozenset({"swim", "hunt", "neck", "crawl", "hop", "passive"})


@dataclass
class Organism:
    id: int
    species: str
    pos: np.ndarray  # µm
    heading: float  # rad, image coordinates
    speed: float  # µm/s, this individual's cruising speed
    length_um: float
    width_um: float
    seed: int
    state: str = "swim"
    timer: float = 0.0
    phase: float = 0.0
    wobble_phase: float = 0.0
    anchor: np.ndarray | None = None
    base_heading: float = 0.0
    contraction: float = 0.0
    neck: float = 0.0  # µm
    neck_angle: float = 0.0
    proboscis_angle: float = 0.0
    blob_phase: float = 0.0
    swell: float = 1.0
    shrink: float = 1.0
    visible: bool = True
    target: int | None = None
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))
    next_hop: float = 0.0
    reach: float = 1.0  # per-individual neck reach fraction
    grace: float = 0.0  # seconds after an avoiding reaction during which bumps are ignored
    z: float = 0.0  # µm above the chamber floor; 0 everywhere in a flat (depth 0) world


@dataclass(frozen=True)
class Event:
    frame: int
    t: float
    kind: str
    actor: int
    subject: int
    x: float  # µm
    y: float


def _dir(a: float) -> np.ndarray:
    return np.array([math.cos(a), math.sin(a)])


def parse_cast(s: str, species: dict[str, Species]) -> dict[str, int]:
    """``"paramecium=8,didinium=2"`` -> {"paramecium": 8, "didinium": 2}."""
    out: dict[str, int] = {}
    for item in filter(None, (x.strip() for x in s.split(","))):
        name, _, n = item.partition("=")
        if name not in species:
            raise ValueError(f"unknown species {name!r}; known: {sorted(species)}")
        try:
            count = int(n) if n else 1
        except ValueError as e:
            raise ValueError(f"bad count for {name}: {n!r}") from e
        if count < 0:
            raise ValueError(f"negative count for {name}")
        out[name] = out.get(name, 0) + count
    return out


class World:
    """The chamber: a ``size_um`` rectangle seen from above, walls on all sides."""

    def __init__(
        self,
        cast: dict[str, int],
        size_um: tuple[float, float],
        seed: int = 0,
        species: dict[str, Species] | None = None,
        drift_um_s: float = 25.0,
        drift_period_s: float = 90.0,
        depth_um: float = 0.0,
        dof_um: float = 30.0,
        focus_um: float | None = None,
        z_walk: float = Z_WALK_UM_SQRT_S,
    ) -> None:
        if depth_um < 0 or dof_um <= 0 or z_walk < 0:
            raise ValueError("depth_um >= 0, dof_um > 0, z_walk >= 0")
        self.species = species or SPECIES
        self.w, self.h = float(size_um[0]), float(size_um[1])
        self.depth = float(depth_um)
        self.dof = float(dof_um)
        self.focus = self.depth / 2 if focus_um is None else float(focus_um)
        if not 0 <= self.focus <= self.depth:
            raise ValueError(f"focus_um must lie in [0, {self.depth}]")
        self.z_walk = float(z_walk)
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.frame = 0
        self.drift_um_s = drift_um_s
        self.drift_period = max(1e-3, drift_period_s)
        self.drift_phase = float(self.rng.uniform(0, 2 * math.pi))
        self.orgs: list[Organism] = []
        self.events: list[Event] = []
        self._by_id: dict[int, Organism] = {}
        for name, n in cast.items():
            for _ in range(n):
                self._spawn(name)

    # ---- setup -------------------------------------------------------------
    def _spawn(self, name: str) -> Organism:
        spec = self.species[name]
        m = spec.motion
        rng = self.rng
        length = spec.length_um * float(np.clip(rng.normal(1, spec.length_cv), 0.4, 2.5))
        width = length * spec.aspect
        speed = (m.speed or m.hop_speed) * float(np.clip(rng.normal(1, m.speed_cv), 0.3, 2.0))
        o = Organism(
            id=len(self.orgs) + 1,
            species=name,
            pos=np.zeros(2),
            heading=float(rng.uniform(0, 2 * math.pi)),
            speed=speed,
            length_um=length,
            width_um=width,
            seed=int(rng.integers(0, 2**31 - 1)),
            phase=float(rng.uniform(0, 1)),
            wobble_phase=float(rng.uniform(0, 2 * math.pi)),
            blob_phase=float(rng.uniform(0, 1)),
            reach=float(rng.uniform(0.6, 1.0)),
        )
        if m.kind == "sessile":
            # foot on a wall, bell pointing in
            side = int(rng.integers(0, 4))
            inset = 0.06
            if side == 0:
                o.anchor = np.array([self.w * inset, rng.uniform(0.2, 0.8) * self.h])
                o.base_heading = 0.0
            elif side == 1:
                o.anchor = np.array([self.w * (1 - inset), rng.uniform(0.2, 0.8) * self.h])
                o.base_heading = math.pi
            elif side == 2:
                o.anchor = np.array([rng.uniform(0.2, 0.8) * self.w, self.h * inset])
                o.base_heading = math.pi / 2
            else:
                o.anchor = np.array([rng.uniform(0.2, 0.8) * self.w, self.h * (1 - inset)])
                o.base_heading = -math.pi / 2
            o.base_heading += float(rng.uniform(-0.5, 0.5))
            o.heading = o.base_heading
            o.pos = o.anchor + _dir(o.heading) * length / 2
            o.state = "extended"
        else:
            # hunters start well clear of everything so the first strike is a hunt, not a spawn
            o.pos = self._free_spot(length, name == "debris", 2.5 if m.kind == "hunt" else 1.0)
            if m.kind == "anchored":
                o.state = "anchored"
                o.base_heading = o.heading
                o.anchor = o.pos - _dir(o.heading) * length / 2
            elif m.kind == "hop":
                o.next_hop = float(rng.exponential(1 / max(m.hop_rate, 1e-6)))
            elif m.kind == "passive":
                o.state = "passive"
        if self.depth > 0:  # drawn last so a flat world consumes the same random stream as before
            o.z = float(rng.uniform(0, self.depth))
        self.orgs.append(o)
        self._by_id[o.id] = o
        return o

    def _free_spot(self, length: float, debris: bool, clearance: float = 1.0) -> np.ndarray:
        m = min(length * 0.6, 0.25 * min(self.w, self.h))
        p = self.rng.uniform([m, m], [self.w - m, self.h - m])
        for _ in range(300):
            if debris:
                return p
            ok = True
            for o in self.orgs:
                if o.species == "debris":
                    continue
                if np.linalg.norm(p - o.pos) < 0.7 * clearance * (length + o.length_um):
                    ok = False
                    break
            if ok:
                return p
            p = self.rng.uniform([m, m], [self.w - m, self.h - m])
        return p  # crowded chamber: overlap allowed

    # ---- dynamics ----------------------------------------------------------
    def drift(self) -> np.ndarray:
        """Convection: a slow current that rotates over ``drift_period`` seconds."""
        a = self.drift_phase + 2 * math.pi * self.t / self.drift_period
        return self.drift_um_s * _dir(a)

    def _walls(self, o: Organism, margin: float | None = None) -> bool:
        m = margin if margin is not None else min(0.3 * o.length_um, 0.2 * min(self.w, self.h))
        hit = False
        if o.pos[0] < m or o.pos[0] > self.w - m:
            o.heading = math.pi - o.heading
            o.vel[0] = -o.vel[0]
            o.pos[0] = float(np.clip(o.pos[0], m, self.w - m))
            hit = True
        if o.pos[1] < m or o.pos[1] > self.h - m:
            o.heading = -o.heading
            o.vel[1] = -o.vel[1]
            o.pos[1] = float(np.clip(o.pos[1], m, self.h - m))
            hit = True
        return hit

    def _near_wall(self, o: Organism) -> bool:
        m = 0.35 * o.length_um
        return bool(o.pos[0] < m or o.pos[0] > self.w - m or o.pos[1] < m or o.pos[1] > self.h - m)

    def _thickness(self, o: Organism) -> float:
        return o.width_um * self.species[o.species].thick

    def _same_layer(self, o: Organism, p: Organism) -> bool:
        """True when the two bodies overlap in Z, i.e. could actually touch."""
        return abs(o.z - p.z) < 0.5 * (self._thickness(o) + self._thickness(p))

    def _bumped(self, o: Organism) -> bool:
        if self._near_wall(o):
            return True
        for p in self.orgs:
            if p is o or not p.visible or p.species == "debris":
                continue
            close = np.linalg.norm(p.pos - o.pos) < 0.3 * (o.length_um + p.length_um)
            if close and self._same_layer(o, p):
                return True
        return False

    def _swimmers_near(self, point: np.ndarray, radius: float) -> bool:
        for p in self.orgs:
            if not p.visible or self.species[p.species].motion.kind not in ("swim", "hunt", "hop"):
                continue
            if p.state in ("caught", "ingest"):
                continue
            if np.linalg.norm(p.pos - point) < radius + 0.5 * p.length_um:
                return True
        return False

    def _log(self, kind: str, actor: Organism, subject: Organism | None = None) -> None:
        self.events.append(
            Event(
                self.frame,
                self.t,
                kind,
                actor.id,
                subject.id if subject else 0,
                float(actor.pos[0]),
                float(actor.pos[1]),
            )
        )

    def step(self, dt: float) -> None:
        drift = self.drift()
        for o in self.orgs:
            kind = self.species[o.species].motion.kind
            getattr(self, f"_step_{kind}")(o, dt, drift)
            # caught prey rides its predator's Z; everything else free wanders
            walks = kind in _Z_WALKERS and o.visible and o.state != "caught"
            if walks and self.depth > 0 and self.z_walk > 0:
                o.z += self.z_walk * math.sqrt(dt) * float(self.rng.normal())
                o.z = float(np.clip(o.z, 0.0, self.depth))
        self.t += dt
        self.frame += 1

    def _random_walk(self, o: Organism, dt: float, speed: float, drift: np.ndarray) -> None:
        m = self.species[o.species].motion
        o.heading += m.turn_sigma * math.sqrt(dt) * float(self.rng.normal())
        if m.wobble_amp and m.wobble_hz:
            w = 2 * math.pi * m.wobble_hz
            o.heading += m.wobble_amp * w * math.cos(w * self.t + o.wobble_phase) * dt
        o.pos += _dir(o.heading) * speed * dt + drift * dt

    def _step_swim(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        if not o.visible or o.state == "caught":
            return
        m = self.species[o.species].motion
        o.phase = (o.phase + 25 * dt) % 1.0
        if o.state == "avoid":
            o.timer -= dt
            o.pos -= _dir(o.heading) * 0.6 * o.speed * dt
            o.pos += drift * dt
            if o.timer <= 0:
                turn = abs(float(self.rng.normal(m.avoid_turn, 0.3)))
                o.heading += turn * (1 if self.rng.random() < 0.5 else -1)
                if self._near_wall(o):
                    # the turn must actually leave the wall, or it bounces forever
                    inward = np.array([self.w / 2, self.h / 2]) - o.pos
                    o.heading = math.atan2(inward[1], inward[0]) + float(self.rng.normal(0, 0.6))
                o.state, o.grace = "swim", 0.5
        else:
            o.grace = max(0.0, o.grace - dt)
            self._random_walk(o, dt, o.speed, drift)
            if o.grace <= 0 and self._bumped(o):
                o.state = "avoid"
                o.timer = m.avoid_time
        self._walls(o)

    def _step_hunt(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        m = self.species[o.species].motion
        o.phase = (o.phase + 25 * dt) % 1.0
        if o.state == "swim":
            self._random_walk(o, dt, o.speed, drift)
            self._walls(o)
            best, bd = None, float("inf")
            for p in self.orgs:
                if p.species != "paramecium" or not p.visible or p.state == "caught":
                    continue
                d = float(np.linalg.norm(p.pos - o.pos)) - 0.5 * p.length_um
                if d < m.strike_radius and d < bd and self._same_layer(o, p):
                    best, bd = p, d
            if best is not None:
                o.state, o.timer, o.target = "ingest", m.ingest_time, best.id
                best.state, best.target = "caught", o.id
                o.heading = math.atan2(*(best.pos - o.pos)[::-1])
                self._log("capture", o, best)
        elif o.state == "ingest":
            prey = self._by_id[o.target] if o.target is not None else None
            o.timer -= dt
            k = float(np.clip(1 - o.timer / max(m.ingest_time, 1e-6), 0, 1))
            o.pos += drift * dt
            o.swell = 1 + 0.35 * k
            if prey is not None:
                snout = o.pos + _dir(o.heading) * 0.5 * o.length_um
                prey.pos = snout + (o.pos - snout) * k
                prey.heading = o.heading + math.pi / 2
                prey.shrink = 1 - 0.9 * k
                prey.z = o.z
            if o.timer <= 0:
                if prey is not None:
                    prey.visible, prey.state = False, "eaten"
                    self._log("ingested", o, prey)
                o.state, o.timer, o.target = "digest", m.digest_time, None
        else:  # digest
            o.timer -= dt
            o.swell = 1 + 0.35 * max(0.0, o.timer / max(m.digest_time, 1e-6))
            self._random_walk(o, dt, m.digest_speed, drift)
            self._walls(o)
            if o.timer <= 0:
                o.state, o.swell = "swim", 1.0

    def _step_sessile(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        m = self.species[o.species].motion
        o.phase = (o.phase + 20 * dt) % 1.0
        o.heading = o.base_heading + 0.12 * math.sin(2 * math.pi * 0.3 * self.t + o.seed % 7)
        if o.contraction < 0.05:
            bell = o.anchor + _dir(o.heading) * o.length_um
            if self._swimmers_near(bell, m.contract_radius) or (
                self.rng.random() < m.contract_rate * dt
            ):
                o.contraction, o.timer, o.state = 1.0, m.reextend_time, "contracted"
                self._log("contraction", o)
        else:
            o.timer -= dt
            o.contraction = max(0.0, o.timer / max(m.reextend_time, 1e-6)) ** 1.5
            if o.contraction < 0.05:
                o.contraction, o.state = 0.0, "extended"
        le = stentor_length(o.length_um, o.contraction)
        o.pos = o.anchor + _dir(o.heading) * le / 2

    def _step_anchored(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        m = self.species[o.species].motion
        o.phase = (o.phase + 10 * dt) % 1.0
        if o.state == "anchored":
            o.contraction = 0.3 + 0.3 * math.sin(2 * math.pi * 0.25 * self.t + o.seed % 5)
            o.heading = o.base_heading + 0.25 * math.sin(2 * math.pi * 0.4 * self.t + o.seed % 3)
            le = o.length_um * (1 - 0.35 * o.contraction)
            o.pos = o.anchor + _dir(o.heading) * le / 2
            if self.rng.random() < m.release_rate * dt:
                o.state, o.timer, o.contraction = "free", m.release_time, 0.0
                self._log("release", o)
        else:
            o.timer -= dt
            self._random_walk(o, dt, o.speed, drift)
            self._walls(o)
            if o.timer <= 0:
                o.state, o.base_heading = "anchored", o.heading
                o.anchor = o.pos - _dir(o.heading) * o.length_um / 2

    def _step_neck(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        m = self.species[o.species].motion
        o.phase = (o.phase + 15 * dt) % 1.0
        self._random_walk(o, dt, o.speed, drift)
        self._walls(o)
        cycle = (self.t * m.neck_hz + o.seed % 100 / 100) % 1.0
        if cycle < 0.15:  # whips out fast
            ext = (cycle / 0.15) ** 0.5
        elif cycle < 0.6:  # searches
            ext = 1.0
        else:  # retracts
            ext = 1 - (cycle - 0.6) / 0.4
        o.neck = ext * m.neck_reach * o.reach
        o.neck_angle = 1.0 * math.sin(2 * math.pi * 1.3 * m.neck_hz * self.t + o.seed % 11)
        o.state = "extended" if ext > 0.3 else "retracted"

    def _step_crawl(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        o.phase = (o.phase + 15 * dt) % 1.0
        self._random_walk(o, dt, o.speed, drift)
        self._walls(o)
        o.proboscis_angle = 0.9 * math.sin(2 * math.pi * 0.8 * self.t + o.seed % 13)

    def _step_drift(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        # stuck to the glass: creeps, does not ride the current
        self._random_walk(o, dt, o.speed, np.zeros(2))
        self._walls(o)
        o.blob_phase = (o.blob_phase + 0.03 * dt) % 1.0
        o.state = "creep"

    def _step_hop(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        m = self.species[o.species].motion
        o.next_hop -= dt
        if o.next_hop <= 0 and o.timer <= 0:
            o.heading += float(self.rng.normal(0, 1.2))
            o.vel = _dir(o.heading) * o.speed
            o.timer = m.hop_time
            o.next_hop = float(self.rng.exponential(1 / max(m.hop_rate, 1e-6)))
            o.state = "hop"
        if o.timer > 0:
            o.timer -= dt
            o.pos += o.vel * dt
            o.phase = (o.phase + 12 * dt) % 1.0
        else:
            o.vel *= math.exp(-dt / 0.08)
            o.pos += o.vel * dt + drift * dt
            o.phase = (o.phase + 3 * dt) % 1.0
            o.state = "sink"
        self._walls(o)

    def _step_passive(self, o: Organism, dt: float, drift: np.ndarray) -> None:
        o.pos += drift * dt + self.rng.normal(0, 2.0 * math.sqrt(dt), 2)
        self._walls(o, margin=1.0)

    # ---- output ------------------------------------------------------------
    def truth_rows(self, um_per_px: float) -> list[list]:
        rows = []
        for o in self.orgs:
            if not o.visible:
                continue
            rows.append(
                [
                    self.frame,
                    o.id,
                    f"{o.pos[0] / um_per_px:.3f}",
                    f"{o.pos[1] / um_per_px:.3f}",
                    o.species,
                    o.state,
                    f"{o.heading:.4f}",
                    f"{o.length_um * o.shrink / um_per_px:.2f}",
                    f"{o.z:.1f}",
                ]
            )
        return rows


_SPRITE_CACHE: dict[tuple, tuple[np.ndarray, int]] = {}


def defocus_sigma_px(z: float, focus: float, dof: float, um_per_px: float) -> float:
    """Gaussian sigma in px for a body ``z`` µm from the focal plane: zero inside
    the depth of field, then linear in the distance beyond it."""
    excess = max(0.0, abs(z - focus) - 0.5 * dof)
    return DEFOCUS_SIGMA_UM_PER_UM * excess / um_per_px


def defocus(sig: np.ndarray, sigma_px: float) -> np.ndarray:
    """Blur a sprite signal, padding the canvas so the spread is not clipped."""
    if sigma_px < 0.05:
        return sig
    pad = int(math.ceil(3 * sigma_px))
    padded = cv2.copyMakeBorder(sig, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    out = cv2.GaussianBlur(padded, (0, 0), sigma_px)
    return out.reshape(padded.shape[0], padded.shape[1], 2)


def render(
    world: World,
    size: tuple[int, int],
    um_per_px: float,
    polarity: str,
    rng: np.random.Generator,
    noise: float = 6.0,
    blur_um: float = 0.0,
) -> np.ndarray:
    """One BGR frame of the world as it stands.

    ``blur_um`` is the optics' resolution floor as a full width at half maximum
    in micrometres (the TOMLOV sits at 10 to 20 µm; a 4x objective on a
    global-shutter sensor resolves finer than a pixel at 1.5 µm/px, so 0). It is
    applied before the sensor noise, as optics come before the sensor.
    """
    if polarity not in POLARITIES:
        raise ValueError(f"polarity must be one of {POLARITIES}, got {polarity!r}")
    if blur_um < 0:
        raise ValueError(f"blur_um must be >= 0, got {blur_um}")
    w, h = size
    bright = polarity == "brightfield"
    img = np.full((h, w), 225.0 if bright else 18.0, np.float32)
    # debris first, then far-from-focus before in-focus so a sharp body draws over a soft one
    order = sorted(
        world.orgs,
        key=lambda o: (
            world.species[o.species].motion.kind != "passive",
            -abs(o.z - world.focus),
        ),
    )
    for o in order:
        if not o.visible:
            continue
        spec = world.species[o.species]
        st = SpriteState(
            length_px=o.length_um / um_per_px,
            width_px=o.width_um / um_per_px,
            heading=o.heading,
            phase=o.phase,
            contraction=o.contraction,
            neck=o.neck / um_per_px,
            neck_angle=o.neck_angle,
            proboscis_angle=o.proboscis_angle,
            blob_phase=o.blob_phase,
            swell=o.swell,
            shrink=o.shrink,
            seed=o.seed,
        )
        if spec.motion.kind == "passive":
            key = (id(world), o.id)
            if key not in _SPRITE_CACHE:
                _SPRITE_CACHE[key] = render_sprite(spec, st, rng)
            sig, _ = _SPRITE_CACHE[key]
        else:
            sig, _ = render_sprite(spec, st, rng)
        if world.depth > 0:
            sig = defocus(sig, defocus_sigma_px(o.z, world.focus, world.dof, um_per_px))
        composite(img, sig, o.pos[0] / um_per_px, o.pos[1] / um_per_px, polarity)
    sigma_px = blur_um / um_per_px / 2.355  # FWHM -> sigma
    if sigma_px > 0.05:
        img = cv2.GaussianBlur(img, (0, 0), sigma_px)
    img += rng.normal(0, noise, img.shape).astype(np.float32)
    gray = np.clip(img, 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def write_clip(
    out: Path,
    world: World,
    frames: int,
    fps: float,
    size: tuple[int, int],
    um_per_px: float,
    polarity: str,
    seed: int,
    noise: float = 6.0,
    sidecar: dict | None = None,
    blur_um: float = 0.0,
) -> dict[str, Path]:
    """Run ``world`` for ``frames`` and encode it; returns the paths written."""
    w, h = size
    out.parent.mkdir(parents=True, exist_ok=True)
    wr = cv2.VideoWriter(str(out), cv2.VideoWriter.fourcc(*"mp4v"), fps, (w, h))
    if not wr.isOpened():
        raise RuntimeError(f"cannot open writer: {out}")
    rng = np.random.default_rng(seed + 7_919)
    truth = out.with_name(out.stem + "_truth.csv")
    events = out.with_name(out.stem + "_events.csv")
    dt = 1.0 / fps
    with truth.open("w", newline="") as fh:
        cw = csv.writer(fh)
        cw.writerow(
            ["frame", "obj_id", "x", "y", "species", "state", "heading", "length_px", "z_um"]
        )
        for _ in range(frames):
            cw.writerows(world.truth_rows(um_per_px))
            wr.write(render(world, size, um_per_px, polarity, rng, noise=noise, blur_um=blur_um))
            world.step(dt)
    wr.release()
    _SPRITE_CACHE.clear()
    with events.open("w", newline="") as fh:
        cw = csv.writer(fh)
        cw.writerow(["frame", "t", "kind", "actor", "subject", "x", "y"])
        for e in world.events:
            cw.writerow(
                [
                    e.frame,
                    f"{e.t:.3f}",
                    e.kind,
                    e.actor,
                    e.subject,
                    f"{e.x / um_per_px:.2f}",
                    f"{e.y / um_per_px:.2f}",
                ]
            )
    paths = {"clip": out, "truth": truth, "events": events}
    if sidecar is not None:
        sc = out.with_suffix(".json")
        sc.write_text(json.dumps(sidecar, indent=1) + "\n")
        paths["sidecar"] = sc
    return paths


def _size(s: str) -> tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        w, h = int(w), int(h)
    except ValueError as e:
        raise argparse.ArgumentTypeError("expected WxH, e.g. 960x720") from e
    if w < 32 or h < 32:
        raise argparse.ArgumentTypeError("size must be at least 32x32")
    return w, h


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", type=Path, help="output .mp4")
    p.add_argument("--cast", default=DEFAULT_CAST, help="species=count,... (default: %(default)s)")
    p.add_argument("--frames", type=int, default=300)
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--size", type=_size, default=(640, 480), help="frame WxH px")
    p.add_argument("--um-per-px", type=float, default=3.0, help="scale (AR0234 at 4x: 1.5)")
    p.add_argument("--polarity", choices=POLARITIES, default="darkfield")
    p.add_argument("--drift", type=float, default=25.0, help="convection speed, µm/s")
    p.add_argument("--drift-period", type=float, default=90.0, help="current rotation period, s")
    p.add_argument("--noise", type=float, default=6.0, help="sensor noise sigma")
    p.add_argument("--depth", type=float, default=150.0, help="chamber depth, µm (0 = flat sim)")
    p.add_argument("--dof", type=float, default=30.0, help="depth of field, µm")
    p.add_argument("--focus", type=float, help="focal plane height, µm (default: depth/2)")
    p.add_argument(
        "--blur-um",
        type=float,
        default=0.0,
        help="optical resolution floor, FWHM in µm (TOMLOV: 10-20; AR0234 at 4x: 0)",
    )
    p.add_argument("--params", type=Path, help="JSON overriding species.py numbers")
    p.add_argument("--dump-params", action="store_true", help="print the species table and exit")
    p.add_argument("--seed", type=int, default=0)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        species = load_params(a.params.read_text()) if a.params else dict(SPECIES)
    except (OSError, ValueError) as e:
        print(f"ecosim: bad --params: {e}", file=sys.stderr)
        return 2
    if a.dump_params:
        sys.stdout.write(dump_params(species) + "\n")
        return 0
    if a.out is None:
        print("ecosim: --out is required (or --dump-params)", file=sys.stderr)
        return 2
    if a.frames < 1 or a.fps <= 0 or a.um_per_px <= 0 or a.blur_um < 0:
        print("ecosim: frames >= 1, fps > 0, um-per-px > 0", file=sys.stderr)
        return 2
    try:
        cast = parse_cast(a.cast, species)
    except ValueError as e:
        print(f"ecosim: bad --cast: {e}", file=sys.stderr)
        return 2
    w, h = a.size
    try:
        world = World(
            cast,
            (w * a.um_per_px, h * a.um_per_px),
            seed=a.seed,
            species=species,
            drift_um_s=a.drift,
            drift_period_s=a.drift_period,
            depth_um=a.depth,
            dof_um=a.dof,
            focus_um=a.focus,
        )
    except ValueError as e:
        print(f"ecosim: bad --depth/--dof/--focus: {e}", file=sys.stderr)
        return 2
    sidecar = {
        "source": "ecosim",
        "illumination": a.polarity,
        "um_per_px": a.um_per_px,
        "fps": a.fps,
        "size": [w, h],
        "frames": a.frames,
        "seed": a.seed,
        "cast": cast,
        "drift_um_s": a.drift,
        "drift_period_s": a.drift_period,
        "depth_um": world.depth,
        "dof_um": world.dof,
        "focus_um": world.focus,
        "blur_um": a.blur_um,
        "noise": a.noise,
        "species": json.loads(dump_params({k: species[k] for k in cast})),
    }
    paths = write_clip(
        a.out,
        world,
        a.frames,
        a.fps,
        a.size,
        a.um_per_px,
        a.polarity,
        a.seed,
        a.noise,
        sidecar,
        blur_um=a.blur_um,
    )
    kinds = {k: sum(1 for e in world.events if e.kind == k) for k in EVENT_KINDS}
    alive = sum(1 for o in world.orgs if o.visible and o.species != "debris")
    print(
        f"{paths['clip']} ({a.frames} frames, {len(world.orgs)} objects, {alive} alive) "
        f"events={kinds} + {paths['truth'].name}, {paths['events'].name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
