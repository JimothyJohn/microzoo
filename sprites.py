#!/usr/bin/env python3
"""sprites.py: procedural, animatable sprites for every species in species.py.

A sprite is rendered in a body-local frame (anterior along +x, centred on the
body centre), textured with a seeded granule field so the speckle rides with
the body, then rotated to its heading. Each render returns two signal maps in
[0, 1]: how much *brighter* than a darkfield background, and how much *darker*
than a brightfield background. ``composite`` applies either to a frame.

The look is taken from darkfield references (references/images.json): a thin
bright pellicle rim, a dim speckled translucent interior, bright food vacuoles,
a darker macronucleus, a faint cilia halo. Under brightfield the same anatomy
reads as a dark rim, grey interior, pale vacuoles.

    python sprites.py --sheet docs/media/sprites.png --atlas docs/media/sprites.json

writes one sprite sheet per polarity (rows = species, columns = animation
phases) and an atlas describing the cells, for the docs page and the tank.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling module under python -I
from species import SPECIES, Species  # noqa: E402

POLARITIES = ("darkfield", "brightfield")

__all__ = [
    "POLARITIES",
    "SpriteState",
    "canvas_px",
    "composite",
    "demo_state",
    "render_sprite",
    "sprite_sheet",
    "stentor_length",
]


@dataclass
class SpriteState:
    """Per-frame pose of one organism, in pixels and radians."""

    length_px: float
    width_px: float
    heading: float = 0.0  # rad, image coordinates (y down)
    phase: float = 0.0  # 0..1 animation cycle (cilia/corona/antennae)
    contraction: float = 0.0  # 0 extended .. 1 contracted (Stentor, rotifer)
    neck: float = 0.0  # px, Lacrymaria neck length
    neck_angle: float = 0.0  # rad off the body axis
    proboscis_angle: float = 0.0  # rad (Dileptus)
    blob_phase: float = 0.0  # amoeba / debris outline drift
    swell: float = 1.0  # width multiplier (Didinium after a meal)
    shrink: float = 1.0  # whole-sprite scale (prey being ingested)
    seed: int = 0  # texture + vacuole layout


def stentor_length(length: float, contraction: float) -> float:
    """Body length of a Stentor at ``contraction`` (0 trumpet .. 1 ball)."""
    return length * (1 - 0.75 * contraction)


def canvas_px(spec: Species, length_px: float, width_px: float, neck_reach_px: float = 0) -> int:
    """Square local canvas side that fits the sprite in every pose (odd, >= 9)."""
    # snouts, feet and corona discs poke past the half length; necks and antennae further
    reach = length_px * 0.7 + (neck_reach_px if spec.look.neck else 0.0)
    if spec.look.antennae:
        reach = max(reach, length_px * 0.5 + length_px * 0.45)
    side = int(math.ceil(2 * max(reach, width_px * 0.5) * 1.12)) + 6
    return max(9, side | 1)


def _polygon(spec: Species, st: SpriteState, n: int = 72) -> np.ndarray:
    """Body outline in local px, (n, 2). Anterior at +x."""
    ln = st.length_px * st.shrink
    wd = st.width_px * st.shrink * st.swell
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    look = spec.look
    if look.trumpet:
        c = st.contraction
        le = stentor_length(ln, c)
        u = np.linspace(0, 1, n // 2)  # 0 at foot (-x) .. 1 at bell (+x)
        trumpet = 0.5 * wd * (0.12 + 0.88 * u**1.5)
        ball = 0.5 * le * np.sqrt(np.clip(1 - (2 * u - 1) ** 2, 0, 1))
        h = ((1 - c) * trumpet + c * ball) * _round_ends(u, 0.08, 0.06)
        return _mirror(-0.5 * le + le * u, h)
    if look.corona:
        le = ln * (1 - 0.35 * st.contraction)
        u = np.linspace(0, 1, n // 2)
        h = 0.5 * wd * np.sin(math.pi * u) ** 0.6 * (0.35 + 0.65 * u) * _round_ends(u, 0.02, 0.1)
        return _mirror(-0.5 * le + le * u, h)
    if look.blob:
        rng = np.random.default_rng(st.seed)
        amp = rng.uniform(0.08, 0.22, 4)
        ph = rng.uniform(0, 2 * math.pi, 4)
        om = rng.uniform(0.5, 1.5, 4)
        r = np.ones_like(t)
        for k in range(4):
            r += amp[k] * np.sin((k + 2) * t + ph[k] + 2 * math.pi * st.blob_phase * om[k])
        return np.stack([0.5 * ln * r * np.cos(t), 0.5 * wd * r * np.sin(t)], axis=1)
    if look.belts:  # Didinium barrel
        return np.stack(
            [0.5 * ln * np.cos(t), 0.5 * wd * np.sign(np.sin(t)) * np.abs(np.sin(t)) ** 0.55],
            axis=1,
        )
    if look.proboscis:  # Dileptus: ellipse over the rear 2/3; trunk drawn separately
        cx = -ln / 6
        return np.stack([cx + (ln / 3) * np.cos(t), 0.5 * wd * np.sin(t)], axis=1)
    if look.antennae:  # Daphnia: oval, tail spine added separately
        return np.stack(
            [0.4 * ln * np.cos(t), 0.5 * wd * np.sin(t) * (1 + 0.1 * np.cos(t))], axis=1
        )
    if look.neck:  # Lacrymaria teardrop, pointed toward the neck
        return np.stack(
            [0.5 * ln * np.cos(t), 0.5 * wd * np.sin(t) * (1 - 0.35 * np.cos(t))], axis=1
        )
    # Paramecium slipper: rounder anterior, narrower posterior
    return np.stack([0.5 * ln * np.cos(t), 0.5 * wd * np.sin(t) * (1 + 0.2 * np.cos(t))], axis=1)


def _round_ends(u: np.ndarray, foot: float, bell: float) -> np.ndarray:
    """Taper factor that rounds a half-width profile at u=0 and u=1."""
    a = np.sqrt(np.clip(1 - np.clip((foot - u) / max(foot, 1e-6), 0, 1) ** 2, 0, 1))
    b = np.sqrt(np.clip(1 - np.clip((u - (1 - bell)) / max(bell, 1e-6), 0, 1) ** 2, 0, 1))
    return a * b


def _mirror(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Closed outline from a half-width profile: top edge left->right, bottom back."""
    top = np.stack([x, -h], axis=1)
    bottom = np.stack([x[::-1], h[::-1]], axis=1)
    return np.concatenate([top, bottom], axis=0)


def _fill(canvas: np.ndarray, pts: np.ndarray, value: float = 1.0) -> None:
    c = canvas.shape[0] // 2
    p = np.round((pts + c) * 16).astype(np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(canvas, [p], value, lineType=cv2.LINE_AA, shift=4)


def _line(canvas: np.ndarray, pts: np.ndarray, thickness: int, value: float = 1.0) -> None:
    c = canvas.shape[0] // 2
    p = np.round((pts + c) * 16).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(canvas, [p], False, value, max(1, thickness), lineType=cv2.LINE_AA, shift=4)


def _bezier(p0, p1, p2, n: int = 24) -> np.ndarray:
    s = np.linspace(0, 1, n)[:, None]
    return (1 - s) ** 2 * p0 + 2 * (1 - s) * s * p1 + s**2 * p2


def _features(spec: Species, st: SpriteState, side: int, rng: np.random.Generator):
    """Extra bright structures (lines) and a mask of appendages that count as body."""
    ln = st.length_px * st.shrink
    wd = st.width_px * st.shrink * st.swell
    lines = np.zeros((side, side), np.float32)
    body = np.zeros((side, side), np.float32)
    look = spec.look
    thin = max(1, int(round(0.05 * wd)))
    if look.belts:
        for xb in (0.22, -0.18):
            e = np.stack(
                [
                    np.full(40, xb * ln) + 0.08 * wd * np.cos(np.linspace(0, 2 * math.pi, 40)),
                    0.5 * wd * 0.97 * np.sin(np.linspace(0, 2 * math.pi, 40)),
                ],
                axis=1,
            )
            _line(lines, e, max(1, thin // 2), 0.6)
        snout = np.array([[0.5 * ln, -0.12 * wd], [0.62 * ln, 0.0], [0.5 * ln, 0.12 * wd]])
        _fill(body, snout, 1.0)
    if look.trumpet:
        c = st.contraction
        le = stentor_length(ln, c)
        r = 0.5 * wd * (1 - 0.5 * c)
        a = np.linspace(-0.5 * math.pi, 0.5 * math.pi, 30)
        arc = np.stack([0.5 * le + 0.15 * r * np.cos(a) - 0.1 * r, r * np.sin(a)], axis=1)
        _line(lines, arc, max(1, int(round(0.035 * wd))), 0.55 - 0.4 * c)
    if look.corona:
        le = ln * (1 - 0.35 * st.contraction)
        beat = 0.55 + 0.45 * math.sin(2 * math.pi * st.phase)
        for s in (-1, 1):
            cx, cy = 0.5 * le + 0.05 * wd, s * 0.33 * wd
            a = np.linspace(0, 2 * math.pi, 24)
            disc = np.stack([cx + 0.22 * wd * np.cos(a), cy + 0.22 * wd * np.sin(a)], axis=1)
            _line(lines, disc, max(1, thin // 2), 0.25 + 0.35 * (beat if s > 0 else 1 - beat))
            _fill(body, disc, 1.0)
        foot = np.array([[-0.5 * le, -0.08 * wd], [-0.62 * le, 0.0], [-0.5 * le, 0.08 * wd]])
        _fill(body, foot, 1.0)
    if look.neck:
        reach = st.neck
        if reach > 0.5:
            ang = st.neck_angle
            p0 = np.array([0.5 * ln, 0.0])
            p1 = p0 + 0.55 * reach * np.array([math.cos(0.5 * ang), math.sin(0.5 * ang)])
            p2 = p0 + reach * np.array([math.cos(ang), math.sin(ang)])
            curve = _bezier(p0, p1, p2)
            _line(lines, curve, max(1, int(round(0.1 * wd))), 0.8)
            _line(body, curve, max(1, int(round(0.14 * wd))), 1.0)
            head = np.stack(
                [
                    p2[0] + 0.16 * wd * np.cos(np.linspace(0, 2 * math.pi, 16)),
                    p2[1] + 0.16 * wd * np.sin(np.linspace(0, 2 * math.pi, 16)),
                ],
                axis=1,
            )
            _fill(body, head, 1.0)
            _line(lines, head, 1, 0.9)
    if look.proboscis:
        ang = st.proboscis_angle
        p0 = np.array([ln / 6, 0.0])
        p1 = p0 + np.array([0.2 * ln, 0.12 * ln * math.sin(ang)])
        p2 = p0 + np.array([0.36 * ln * math.cos(ang * 0.6), 0.36 * ln * math.sin(ang)])
        curve = _bezier(p0, p1, p2)
        _line(body, curve[:12], max(1, int(round(0.5 * wd))), 1.0)
        _line(body, curve[10:], max(1, int(round(0.28 * wd))), 1.0)
        _line(lines, curve, 1, 0.5)
    if look.antennae:
        flap = 0.5 + 0.5 * math.sin(2 * math.pi * st.phase)
        for s in (-1, 1):
            p0 = np.array([0.3 * ln, s * 0.15 * wd])
            a = s * (0.6 + 0.5 * flap)
            p1 = p0 + 0.25 * ln * np.array([math.cos(a * 0.5), math.sin(a * 0.5)])
            p2 = p0 + 0.45 * ln * np.array([math.cos(a), math.sin(a)])
            _line(lines, _bezier(p0, p1, p2), max(1, int(round(0.03 * wd))), 0.9)
        spine = np.array([[-0.4 * ln, -0.12 * wd], [-0.62 * ln, 0.0], [-0.4 * ln, 0.12 * wd]])
        _fill(body, spine, 1.0)
        eye = np.array([0.28 * ln, -0.22 * wd])
        cv2.circle(
            lines,
            (int(round(eye[0] + side // 2)), int(round(eye[1] + side // 2))),
            max(1, int(round(0.06 * wd))),
            1.0,
            -1,
            lineType=cv2.LINE_AA,
        )
    return lines, body


def render_sprite(
    spec: Species,
    st: SpriteState,
    rng: np.random.Generator | None = None,
    canvas: int | None = None,
) -> tuple[np.ndarray, int]:
    """(signal, side): ``signal`` is (side, side, 2) float32 in [0, 1]:
    channel 0 = brightness above a darkfield background, channel 1 = darkness
    below a brightfield background. The canvas is centred on the body centre.
    ``rng`` only drives the per-frame cilia flicker; layout comes from
    ``st.seed`` so it is stable across frames.
    """
    ln = st.length_px * st.shrink
    wd = st.width_px * st.shrink * st.swell
    if ln < 1 or wd < 1:
        side = canvas or 9
        return np.zeros((side, side, 2), np.float32), side
    side = canvas or canvas_px(spec, st.length_px, st.width_px, st.neck)
    look = spec.look
    layout = np.random.default_rng(st.seed)
    flick = rng if rng is not None else np.random.default_rng(st.seed ^ 0x5EED)

    mask = np.zeros((side, side), np.float32)
    _fill(mask, _polygon(spec, st), 1.0)
    lines, extra = _features(spec, st, side, layout)
    mask = np.maximum(mask, extra)

    k = max(1, int(round(0.04 * wd)))
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    inner = cv2.erode(mask, kern)
    rim = np.clip(mask - inner, 0, 1)
    rim = cv2.GaussianBlur(rim, (0, 0), 0.5)
    rim /= max(1e-6, float(rim.max()))

    # granule field in the local frame: band-limited noise, fixed per organism
    lo = max(4, side // 6)
    g = layout.normal(0, 1, (lo, lo)).astype(np.float32)
    g = cv2.resize(g, (side, side), interpolation=cv2.INTER_CUBIC)
    g += 0.6 * layout.normal(0, 1, (side, side)).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), max(0.5, 0.012 * wd))
    g = g / max(1e-6, float(np.std(g)))
    g = np.clip(g, -2, 2) / 2

    nuc = np.zeros((side, side), np.float32)
    if look.nucleus > 0:
        c = side // 2
        nx = c + int(round(-0.05 * ln))
        cv2.ellipse(
            nuc,
            (nx, c),
            (max(1, int(round(0.18 * ln))), max(1, int(round(0.22 * wd)))),
            float(layout.uniform(-25, 25)),
            0,
            360,
            1.0,
            -1,
            lineType=cv2.LINE_AA,
        )
        nuc = cv2.GaussianBlur(nuc, (0, 0), max(0.5, 0.03 * wd)) * inner

    vac = np.zeros((side, side), np.float32)
    for _ in range(look.vacuoles):
        a = layout.uniform(0, 2 * math.pi)
        rr = math.sqrt(layout.uniform(0, 1)) * 0.75
        vx = side // 2 + int(round(0.5 * ln * rr * math.cos(a)))
        vy = side // 2 + int(round(0.5 * wd * rr * math.sin(a)))
        cv2.circle(vac, (vx, vy), max(1, int(round(0.07 * wd))), 1.0, -1, lineType=cv2.LINE_AA)
    vac = cv2.GaussianBlur(vac, (0, 0), max(0.5, 0.02 * wd)) * inner * 0.7

    halo = np.zeros_like(mask)
    if look.halo > 0:
        hk = max(1, int(round(0.08 * wd)))
        hker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * hk + 1, 2 * hk + 1))
        halo = np.clip(cv2.dilate(mask, hker) - mask, 0, 1)
        halo = cv2.GaussianBlur(halo, (0, 0), max(0.6, 0.05 * wd))
        halo *= float(flick.uniform(0.6, 1.0))
        halo *= 1 + 0.4 * g  # cilia are not a smooth ring

    interior = inner * (1 + look.granules * g)
    df = (
        look.interior * interior
        + look.rim * rim
        + look.halo * halo
        + 0.55 * vac
        - look.nucleus * look.interior * 0.8 * nuc
        + lines * 0.9
    )
    bf = (
        0.55 * look.interior * 1.6 * inner * (1 + 0.6 * look.granules * g)
        + 0.75 * look.rim * rim
        + 0.5 * look.nucleus * nuc
        - 0.3 * vac
        + 0.35 * look.halo * halo
        + lines * 0.5
    )
    sig = np.stack([np.clip(df, 0, 1), np.clip(bf, 0, 1)], axis=2)
    if st.heading:
        c = side / 2 - 0.5
        m = cv2.getRotationMatrix2D((c, c), -math.degrees(st.heading), 1.0)
        sig = cv2.warpAffine(sig, m, (side, side), flags=cv2.INTER_LINEAR, borderValue=0)
    return sig.astype(np.float32), side


def composite(
    frame: np.ndarray, sig: np.ndarray, cx: float, cy: float, polarity: str, gain: float = 1.0
) -> None:
    """Blend a sprite's signal into a float32 grey frame in place at (cx, cy)."""
    if polarity not in POLARITIES:
        raise ValueError(f"polarity must be one of {POLARITIES}, got {polarity!r}")
    side = sig.shape[0]
    h, w = frame.shape[:2]
    x0 = int(round(cx)) - side // 2
    y0 = int(round(cy)) - side // 2
    fx0, fy0 = max(0, x0), max(0, y0)
    fx1, fy1 = min(w, x0 + side), min(h, y0 + side)
    if fx1 <= fx0 or fy1 <= fy0:
        return
    sx0, sy0 = fx0 - x0, fy0 - y0
    region = frame[fy0:fy1, fx0:fx1]
    if polarity == "darkfield":
        s = sig[sy0 : sy0 + (fy1 - fy0), sx0 : sx0 + (fx1 - fx0), 0] * 255.0 * gain
        np.maximum(region, s, out=region)
    else:
        s = 255.0 - sig[sy0 : sy0 + (fy1 - fy0), sx0 : sx0 + (fx1 - fx0), 1] * 255.0 * gain
        np.minimum(region, s, out=region)


def demo_state(
    spec: Species, phase: float, length_px: float, seed: int = 0, um_per_px: float | None = None
) -> SpriteState:
    """A canonical animation cycle per species, used by the sheet and the docs page."""
    st = SpriteState(length_px=length_px, width_px=length_px * spec.aspect, phase=phase, seed=seed)
    look = spec.look
    scale = um_per_px or (spec.length_um / length_px)
    if look.trumpet:
        # extended most of the cycle, snaps shut at 0.6, re-extends
        st.contraction = 1.0 if 0.6 <= phase < 0.66 else max(0.0, 1 - (phase - 0.6) / 0.34)
        st.contraction = st.contraction if phase >= 0.6 else 0.0
    if look.corona:
        st.contraction = 0.3 + 0.3 * math.sin(2 * math.pi * phase)
    if look.neck:
        st.neck = (0.5 + 0.5 * math.sin(2 * math.pi * phase)) * spec.motion.neck_reach / scale
        st.neck_angle = 0.8 * math.sin(2 * math.pi * phase * 2)
    if look.proboscis:
        st.proboscis_angle = 0.9 * math.sin(2 * math.pi * phase)
    if look.blob:
        st.blob_phase = phase
    return st


def sprite_sheet(
    species: dict[str, Species],
    frames: int = 12,
    cell: int = 160,
    polarity: str = "darkfield",
) -> tuple[np.ndarray, dict]:
    """(sheet uint8 grey, atlas). One row per species, ``frames`` columns.
    Each species is scaled to fit the cell; the atlas records its µm/px."""
    names = list(species)
    sheet = np.full(
        (cell * len(names), cell * frames), 18 if polarity == "darkfield" else 225, np.float32
    )
    atlas = {"cell": cell, "frames": frames, "polarity": polarity, "species": {}}
    for row, name in enumerate(names):
        spec = species[name]
        reach = spec.length_um
        if spec.look.neck:
            reach += spec.motion.neck_reach
        length_px = cell * 0.8 * spec.length_um / reach * (1.6 if spec.look.neck else 1.0)
        length_px = min(length_px, cell * 0.8)
        um_per_px = spec.length_um / length_px
        for col in range(frames):
            st = demo_state(spec, col / frames, length_px, seed=row + 1, um_per_px=um_per_px)
            st.heading = 0.0
            sig, side = render_sprite(spec, st, canvas=cell | 1)
            region = sheet[row * cell : (row + 1) * cell, col * cell : (col + 1) * cell]
            composite(region, sig, cell / 2, cell / 2, polarity)
        atlas["species"][name] = {
            "row": row,
            "um_per_px": round(um_per_px, 4),
            "length_um": spec.length_um,
            "role": spec.role,
        }
    return np.clip(sheet, 0, 255).astype(np.uint8), atlas


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--sheet", type=Path, required=True, help="output PNG (polarity is inserted)")
    p.add_argument("--atlas", type=Path, help="output JSON (default: next to the sheet)")
    p.add_argument("--frames", type=int, default=12)
    p.add_argument("--cell", type=int, default=160)
    p.add_argument("--species", default="", help="comma list (default: all but debris)")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.frames < 1 or a.cell < 16:
        print("sprites: frames >= 1 and cell >= 16", file=sys.stderr)
        return 2
    names = [s for s in a.species.split(",") if s] or [n for n in SPECIES if n != "debris"]
    unknown = [n for n in names if n not in SPECIES]
    if unknown:
        print(f"sprites: unknown species {unknown}; known: {sorted(SPECIES)}", file=sys.stderr)
        return 2
    chosen = {n: SPECIES[n] for n in names}
    atlas_all: dict = {"cell": a.cell, "frames": a.frames, "sheets": {}, "species": {}}
    a.sheet.parent.mkdir(parents=True, exist_ok=True)
    for pol in POLARITIES:
        sheet, atlas = sprite_sheet(chosen, a.frames, a.cell, pol)
        out = a.sheet.with_name(f"{a.sheet.stem}_{pol}{a.sheet.suffix or '.png'}")
        cv2.imwrite(str(out), sheet)
        atlas_all["sheets"][pol] = out.name
        atlas_all["species"] = atlas["species"]
        print(f"{out} {sheet.shape[1]}x{sheet.shape[0]}")
    atlas_path = a.atlas or a.sheet.with_suffix(".json")
    atlas_path.write_text(json.dumps(atlas_all, indent=1) + "\n")
    print(atlas_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
