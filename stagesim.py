#!/usr/bin/env python3
"""stagesim.py: the Meca500 carrying the slide under the microscope, simulated.

Two subcommands:

    table   what this robot means at each magnification: pixel size, field,
            depth of field, the 5 µm repeatability in pixels and against the
            depth of field, the fastest scan that keeps motion blur under a
            pixel, a field-to-field hop and its settle, a coverslip survey,
            and which organisms a follow can keep up with.

    run     an ecosim drop of water on a slide that a SimStage moves under a
            fixed camera. The camera renders what it would see: the view
            window, defocus from the stage's Z, motion blur from the stage's
            velocity during the exposure, flex ringing and servo jitter.
            Modes: hold (sit still), scan (raster the slide field by field),
            follow (jog the stage to keep one organism centred, from its
            position ``--latency`` seconds ago), zsweep (ramp the focus through
            the chamber).

    python stagesim.py table --speed 5000 --acc 50000
    python stagesim.py run --out data/meca_follow.mp4 --mode follow --objective 10x

Writes for ``run``:

    <out>              the camera's view (mp4v)
    <stem>_stage.csv   frame, t, view x/y/z (where the slide really is), cmd x/y/z
                       (what was asked), speed, blur_px, ringing_um, target_id,
                       target_dx_px, target_dy_px
    <stem>_truth.csv   ecosim truth in image pixels (frame, obj_id, x, y, species, ...)
    <stem>.json        sidecar: optics, robot model, mode, and the follow score

Water on the slide: a sealed spacer chamber cannot carry net flow, so its
contents ride the slide (``--chamber sealed``). ``--chamber well`` models an
open well of ``--well-depth`` as a first-order viscous lag behind the slide,
tau = H^2 / (pi^2 nu); it ignores surface waves, so it is a lower bound on
slosh, not a prediction.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling modules under python -I
from ecosim import DEFAULT_CAST, World, parse_cast, render  # noqa: E402
from species import SPECIES  # noqa: E402
from stage import (  # noqa: E402
    MECA_REPEATABILITY_UM,
    SimParams,
    SimStage,
    SlideFrame,
    move_time,
)

WAVELENGTH_UM = 0.55
WATER_NU_UM2_S = 1.0e6  # kinematic viscosity of water, 1 mm²/s


@dataclass(frozen=True)
class Optics:
    name: str
    um_per_px: float  # at the sample, full sensor resolution
    na: float  # 0 = unknown
    mag: float  # objective x relay, at the sensor
    sensor: tuple[int, int] = (1920, 1200)
    pixel_um: float = 3.0

    @property
    def field_um(self) -> tuple[float, float]:
        return self.sensor[0] * self.um_per_px, self.sensor[1] * self.um_per_px

    @property
    def dof_um(self) -> float:
        """lambda/NA^2 + e/(M NA): the formula hardware/HARDWARE.md §4 uses."""
        if self.na <= 0:
            return math.nan
        return WAVELENGTH_UM / self.na**2 + self.pixel_um / (self.mag * self.na)


# AR0234 (3.0 µm, 1920x1200) through the 0.5x relay, as in hardware/HARDWARE.md §4.
# TOMLOV: ecosim's 6 µm/px, unmeasured; its depth of field is unknown.
VIEWS: dict[str, Optics] = {
    "tomlov": Optics("TOMLOV", 6.0, 0.0, 0.5, (1920, 1080)),
    "4x": Optics("4x NA 0.10", 1.5, 0.10, 2.0),
    "10x": Optics("10x NA 0.25", 0.6, 0.25, 5.0),
    "40x": Optics("40x NA 0.65", 0.15, 0.65, 20.0),
}
FOLLOW_CAST = (
    "paramecium",
    "didinium",
    "blepharisma",
    "dileptus",
    "coleps",
    "euplotes",
    "rotifer",
    "halteria",
    "cyclops",
    "daphnia",
)


# ---- the table --------------------------------------------------------------
def settle_time(params: SimParams, dist_um: float, tol_um: float, limit_s: float = 5.0) -> float:
    """Seconds after the commanded move ends until the flex ringing stays under ``tol_um``."""
    p = SimParams(**{**asdict(params), "jitter_um": 0.0, "repeat_um": 0.0})
    st = SimStage(frame=SlideFrame(limits_um=((-1e6, 1e6),) * 3), params=p)
    st.move_to(dist_um, 0.0, 0.0)
    dt = 0.001
    while st.moving:
        st.step(dt)
        if st.t > limit_s:
            return math.inf
    t_end, last_bad = st.t, st.t
    while st.t - t_end < limit_s:
        st.step(dt)
        if st.ringing_um >= tol_um:
            last_bad = st.t
        elif st.t - last_bad > 0.2:
            return last_bad - t_end
    return math.inf


def organism_speeds(names: tuple[str, ...] = FOLLOW_CAST) -> list[tuple[str, float, float]]:
    """(name, cruise µm/s, burst µm/s) from species.py."""
    out = []
    for n in names:
        m = SPECIES[n].motion
        out.append((n, m.speed, max(m.speed, m.hop_speed)))
    return out


def follow_verdict(speed: float, view: Optics, params: SimParams, latency_s: float) -> str:
    """Can a jog servo keep this speed in the field? It has until the organism
    crosses half the field's short side; latency eats the start of that, and
    the stage must reach ``speed`` in what's left."""
    half = min(view.field_um) / 2
    escape = half / speed if speed > 0 else math.inf
    if speed > params.speed_um_s:
        return "no: faster than the speed cap"
    ramp = params.acc_um_s2 / params.jerk_um_s3 if params.jerk_um_s3 > 0 else 0.0
    budget = escape - latency_s - ramp / 2  # the jerk filter delays the response by half its window
    if budget <= 0:
        return f"no: gone in {escape * 1000:.0f} ms"
    need = speed / budget
    # once matched, the remaining lag is speed*latency + speed^2/(2 acc)
    lag = speed * (latency_s + ramp / 2) + speed**2 / (2 * params.acc_um_s2)
    if need > params.acc_um_s2 or lag > half:
        return f"no: needs {need / 1000:.0f} mm/s²"
    return f"yes, lags {lag / view.um_per_px:.0f} px"


def table(params: SimParams, exposure_s: float, latency_s: float, coverslip_mm: float) -> str:
    rp_px = MECA_REPEATABILITY_UM
    lines = [
        f"Meca500 holding the slide: repeatability {rp_px:g} µm (spec), speed "
        f"{params.speed_um_s / 1000:g} mm/s, acceleration {params.acc_um_s2 / 1000:g} mm/s² "
        f"(assumed), jerk {params.jerk_um_s3 / 1000:g} mm/s³, "
        f"flex {params.flex_hz:g} Hz zeta {params.flex_zeta:g} (assumed), "
        f"exposure {exposure_s * 1000:g} ms, latency {latency_s * 1000:g} ms.",
        "",
        "| View | µm/px | Field (mm) | DoF (µm) | 5 µm repeat = | vs DoF | Scan ≤1 px blur "
        "| Field hop + settle | Survey "
        f"{coverslip_mm:g}×{coverslip_mm:g} mm |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for v in VIEWS.values():
        fw, fh = v.field_um
        dof = v.dof_um
        vs_dof = "unknown" if math.isnan(dof) else f"{MECA_REPEATABILITY_UM / dof:.0%}"
        v_scan = v.um_per_px / exposure_s
        hop = move_time(fw, params.speed_um_s, params.acc_um_s2, params.jerk_um_s3)
        settle = settle_time(params, fw, v.um_per_px / 2)
        tiles = math.ceil(coverslip_mm * 1000 / fw) * math.ceil(coverslip_mm * 1000 / fh)
        survey = tiles * (hop + settle + exposure_s)
        dof_s = "—" if math.isnan(dof) else f"{dof:.1f}"
        rp = MECA_REPEATABILITY_UM / v.um_per_px
        lines.append(
            f"| {v.name} | {v.um_per_px:g} | {fw / 1000:.2f} × {fh / 1000:.2f} | {dof_s} "
            f"| {rp:.1f} px | {vs_dof} | {v_scan / 1000:.2f} mm/s "
            f"| {hop * 1000:.0f} + {settle * 1000:.0f} ms | {tiles} tiles, {survey:.0f} s |"
        )
    lines += [
        "",
        "Follow: can a jog servo keep it in the field? (speeds from species.py; burst = hop)",
        "",
        "| Organism | Cruise mm/s | Burst mm/s | " + " | ".join(VIEWS) + " |",
        "|---|---|---|" + "---|" * len(VIEWS),
    ]
    for name, cruise, burst in organism_speeds():
        cells = []
        for v in VIEWS.values():
            c = follow_verdict(cruise, v, params, latency_s)
            if burst > cruise:
                b = follow_verdict(burst, v, params, latency_s)
                c += "; burst " + ("ok" if b.startswith("yes") else "lost")
            cells.append(c)
        lines.append(
            f"| {name} | {cruise / 1000:.2f} | {burst / 1000:.2f} | " + " | ".join(cells) + " |"
        )
    h = 150.0
    lines += [
        "",
        f"Water: a sealed {h:g} µm chamber relaxes viscously in "
        f"{h**2 / (math.pi**2 * WATER_NU_UM2_S) * 1000:.1f} ms and closed walls forbid net flow, "
        "so the sample rides the slide. An open 1 mm well lags by "
        f"{1000.0**2 / (math.pi**2 * WATER_NU_UM2_S) * 1000:.0f} ms plus surface waves.",
    ]
    return "\n".join(lines)


# ---- the run ----------------------------------------------------------------
def scale_cast(cast: dict[str, int], area_ratio: float) -> dict[str, int]:
    return {k: max(1, round(n * area_ratio)) if n else 0 for k, n in cast.items()}


@contextmanager
def framed(world: World, view: np.ndarray, fluid: np.ndarray, size: tuple[int, int], upp: float):
    """Temporarily move every organism into camera coordinates for ``render``:
    the slide's (0, 0) is the world centre, the view is the slide point under
    the optical axis, and the water carries everything by ``fluid`` µm
    relative to the slide. Organisms well outside the frame are hidden for
    speed. Restores positions, visibility and focus on exit."""
    saved = [(o, o.pos.copy(), o.visible) for o in world.orgs]
    focus = world.focus
    w, h = size
    shift = np.array([w * upp / 2, h * upp / 2]) - np.array([world.w / 2, world.h / 2])
    shift = shift - view[:2] + fluid
    margin = max(w, h) * upp * 0.25
    try:
        world.focus = float(view[2])
        for o in world.orgs:
            o.pos = o.pos + shift
            pad = margin + o.length_um
            if not (-pad < o.pos[0] < w * upp + pad and -pad < o.pos[1] < h * upp + pad):
                o.visible = False
        yield
    finally:
        world.focus = focus
        for o, pos, vis in saved:
            o.pos = pos
            o.visible = vis


def motion_blur(img: np.ndarray, d_px: np.ndarray) -> np.ndarray:
    """Smear ``img`` along the exposure's displacement ``d_px`` (box kernel)."""
    n = float(np.hypot(*d_px))
    if n < 0.5:
        return img
    k = int(math.ceil(n)) | 1
    ker = np.zeros((k, k), np.float32)
    c = k // 2
    for s in np.linspace(-0.5, 0.5, 4 * k):
        ker[int(round(c + s * d_px[1])), int(round(c + s * d_px[0]))] += 1
    ker /= ker.sum()
    return cv2.filter2D(img, -1, ker, borderType=cv2.BORDER_REFLECT)


class Follower:
    """Jog servo on one organism, from positions ``latency`` seconds old:
    velocity feed-forward from the last two measurements plus a proportional
    pull toward the predicted position."""

    def __init__(self, species: str, latency_s: float, kp: float, deadband_um: float) -> None:
        self.species = species
        self.latency = latency_s
        self.kp = kp
        self.deadband = deadband_um
        self.target: int | None = None
        self.history: list[tuple[float, np.ndarray]] = []

    def pick(self, world: World, view: np.ndarray, slide_of) -> None:
        cands = [o for o in world.orgs if o.species == self.species and o.visible]
        if not cands:
            self.target = None
            return
        best = min(cands, key=lambda o: float(np.linalg.norm(slide_of(o) - view[:2])))
        self.target = best.id
        self.history.clear()

    def command(self, t: float, world: World, stage: SimStage, slide_of) -> np.ndarray:
        org = next((o for o in world.orgs if o.id == self.target and o.visible), None)
        if org is None:
            self.pick(world, np.array(stage.pose()), slide_of)
            return np.zeros(3)
        self.history.append((t, slide_of(org)))
        seen = [(ts, p) for ts, p in self.history if ts <= t - self.latency + 1e-9]
        # seen is a prefix of history; keep its last two and everything newer
        self.history = self.history[max(0, len(seen) - 2) :]
        if len(seen) < 2:
            return np.zeros(3)
        (t0, p0), (t1, p1) = seen[-2], seen[-1]
        vel = (p1 - p0) / max(t1 - t0, 1e-6)
        pred = p1 + vel * (t - t1)
        err = pred - stage.cmd[:2]
        if float(np.linalg.norm(err)) < self.deadband:
            err = np.zeros(2)
        v = vel + self.kp * err
        sp = float(np.linalg.norm(v))
        cap = stage.params.speed_um_s
        if sp > cap:
            v = v * (cap / sp)
        return np.array([v[0], v[1], 0.0])


def run(a: argparse.Namespace) -> int:
    view_opt = VIEWS[a.objective]
    full_w, full_h = view_opt.sensor
    w, h = a.size if a.size else (full_w // 2, full_h // 2)
    upp = view_opt.um_per_px * full_w / w  # rendered µm/px
    try:
        params = SimParams(
            speed_um_s=a.speed,
            acc_um_s2=a.acc,
            jerk_um_s3=a.jerk * 1000,
            repeat_um=a.repeat,
            flex_hz=a.flex_hz,
            flex_zeta=a.flex_zeta,
            jitter_um=a.jitter,
        )
        base = parse_cast(a.cast or DEFAULT_CAST, SPECIES)
    except ValueError as e:
        print(f"stagesim: {e}", file=sys.stderr)
        return 2
    if a.world:
        ww, wh = a.world
    else:  # room to roam: the tiles plus a field, and never less than 1.5 fields or 4x3 mm
        fw, fh = view_opt.field_um
        nx, ny = a.tiles if a.mode == "scan" else (0, 0)
        ww = max(4000.0, 1.5 * fw, (nx + 1) * fw)
        wh = max(3000.0, 1.5 * fh, (ny + 1) * fh)
    # ecosim's default cast is dense for a 960x720 frame at 3 µm/px
    cast = scale_cast(base, ww * wh / (960 * 720 * 9.0))
    if a.mode == "follow" and cast.get(a.target, 0) == 0:
        cast[a.target] = 2
    depth = a.depth
    world = World(
        cast,
        (ww, wh),
        seed=a.seed,
        depth_um=depth,
        dof_um=view_opt.dof_um if math.isfinite(view_opt.dof_um) else depth,
    )
    half = ((-ww / 2, ww / 2), (-wh / 2, wh / 2), (-50.0, depth + 50.0))
    stage = SimStage(frame=SlideFrame(limits_um=half), params=params, seed=a.seed + 1)
    focus = depth / 2 if a.focus is None else a.focus
    stage.place(0.0, 0.0, focus)
    tau = (a.well_depth**2 / (math.pi**2 * WATER_NU_UM2_S)) if a.chamber == "well" else 0.0
    fluid_abs = np.zeros(2)  # where the water has got to, in slide-motion terms

    def slide_of(o) -> np.ndarray:
        return o.pos - np.array([ww / 2, wh / 2]) + fluid_rel()

    def fluid_rel() -> np.ndarray:
        return fluid_abs - (-stage.cmd[:2]) if tau > 0 else np.zeros(2)

    # mode setup
    follower = None
    plan: list[tuple[float, float, float]] = []
    if a.mode == "follow":
        follower = Follower(a.target, a.latency, a.kp, a.deadband * upp)
        follower.pick(world, stage.cmd, slide_of)
        if follower.target is None:
            print(f"stagesim: no {a.target} in the cast", file=sys.stderr)
            return 2
        tgt = next(o for o in world.orgs if o.id == follower.target)
        p = slide_of(tgt)
        stage.place(float(p[0]), float(p[1]), focus)
    elif a.mode == "scan":
        fw, fh = w * upp, h * upp
        nx, ny = max(1, int(a.tiles[0])), max(1, int(a.tiles[1]))
        for j in range(ny):
            cols = range(nx) if j % 2 == 0 else range(nx - 1, -1, -1)
            for i in range(cols.start, cols.stop, cols.step):
                plan.append(((i - (nx - 1) / 2) * fw, (j - (ny - 1) / 2) * fh, focus))
        try:
            for p in plan:
                stage.frame.check(p)
        except ValueError as e:
            print(f"stagesim: scan leaves the slide: {e}", file=sys.stderr)
            return 2
    elif a.mode == "zsweep":
        stage.set_speed(a.zrate)
        for _ in range(4):
            plan += [(0.0, 0.0, 0.0), (0.0, 0.0, depth)]

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wr = cv2.VideoWriter(str(out), cv2.VideoWriter.fourcc(*"mp4v"), a.fps, (w, h))
    if not wr.isOpened():
        print(f"stagesim: cannot open writer: {out}", file=sys.stderr)
        return 2
    rng = np.random.default_rng(a.seed + 7_919)
    dt = 1.0 / a.fps
    exp = min(a.exposure, dt)
    dwell_until: float | None = None
    plan_i = 0
    errs: list[float] = []
    in_field = 0
    stage_path = out.with_name(out.stem + "_stage.csv")
    truth_path = out.with_name(out.stem + "_truth.csv")
    with stage_path.open("w", newline="") as fs, truth_path.open("w", newline="") as ft:
        cs, ct = csv.writer(fs), csv.writer(ft)
        cs.writerow(
            [
                "frame", "t", "view_x", "view_y", "view_z", "cmd_x", "cmd_y", "cmd_z",
                "speed_um_s", "blur_px", "ringing_um", "target_id", "target_dx_px", "target_dy_px",
            ]
        )  # fmt: skip
        ct.writerow(
            ["frame", "obj_id", "x", "y", "species", "state", "heading", "length_px", "z_um"]
        )
        for f in range(a.frames):
            # controller
            if follower is not None:
                stage.jog(*follower.command(stage.t, world, stage, slide_of))
            elif plan and stage.idle:  # settled: dwell, then the next stop
                if dwell_until is None:
                    dwell_until = stage.t + a.dwell
                elif stage.t >= dwell_until and plan_i < len(plan):
                    stage.move_to(*plan[plan_i])
                    plan_i += 1
                    dwell_until = None
            # physics: the frame interval, the exposure at its end
            p0 = np.array(stage.pose())
            for sub, expose in ((dt - exp, False), (exp, True)):
                if expose:
                    p0 = np.array(stage.pose())
                if sub <= 0:
                    continue
                stage.step(sub)
                if tau > 0:
                    fluid_abs += (-stage.cmd[:2] - fluid_abs) * (1 - math.exp(-sub / tau))
            p1 = np.array(stage.pose())
            world.step(dt)
            blur = (p1[:2] - p0[:2]) / upp
            mid = (p0 + p1) / 2
            # the camera
            with framed(world, mid, fluid_rel(), (w, h), upp):
                frame = render(world, (w, h), upp, a.polarity, rng, noise=0.0)
                ct.writerows([[f, *r[1:]] for r in world.truth_rows(upp)])
            frame = motion_blur(frame, -blur)
            noisy = frame.astype(np.float32) + rng.normal(0, a.noise, frame.shape[:2])[..., None]
            wr.write(np.clip(noisy, 0, 255).astype(np.uint8))
            # bookkeeping
            tid, dx, dy = "", "", ""
            if follower is not None and follower.target is not None:
                org = next((o for o in world.orgs if o.id == follower.target), None)
                if org is not None and org.visible:
                    d = (slide_of(org) - p1[:2]) / upp
                    tid, dx, dy = org.id, f"{d[0]:.2f}", f"{d[1]:.2f}"
                    errs.append(float(np.hypot(*d)))
                    in_field += abs(d[0]) < w / 2 and abs(d[1]) < h / 2
            sp = float(np.linalg.norm(stage.vel))
            cs.writerow(
                [f, f"{stage.t:.4f}", *(f"{v:.3f}" for v in p1), *(f"{v:.3f}" for v in stage.cmd),
                 f"{sp:.1f}", f"{np.hypot(*blur):.2f}", f"{stage.ringing_um:.3f}", tid, dx, dy]
            )  # fmt: skip
    wr.release()
    score = {}
    if follower is not None:
        score = {
            "target": a.target,
            "in_field": in_field / a.frames,
            "rms_err_px": float(np.sqrt(np.mean(np.square(errs)))) if errs else None,
            "max_err_px": max(errs) if errs else None,
        }
    sidecar = {
        "source": "stagesim",
        "mode": a.mode,
        "objective": a.objective,
        "um_per_px": upp,
        "fps": a.fps,
        "exposure_s": exp,
        "size": [w, h],
        "frames": a.frames,
        "seed": a.seed,
        "chamber": a.chamber,
        "depth_um": depth,
        "focus_um": focus,
        "well_tau_s": tau,
        "robot": {**asdict(params), "model": "Meca500", "assumed": ["acc", "flex", "jitter"]},
        "cast": cast,
        "follow": score,
    }
    out.with_suffix(".json").write_text(json.dumps(sidecar, indent=1) + "\n")
    msg = f"{out} ({a.frames} frames, {a.objective}, {upp:.2f} µm/px, mode {a.mode})"
    if score:
        msg += (
            f" follow {a.target}: in field {score['in_field']:.0%}, "
            f"rms {score['rms_err_px'] or 0:.0f} px, max {score['max_err_px'] or 0:.0f} px"
        )
    print(msg)
    return 0


# ---- CLI --------------------------------------------------------------------
def _pair(s: str, kind=float) -> tuple:
    try:
        x, y = s.lower().split("x")
        return kind(x), kind(y)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected AxB, got {s!r}") from e


def _robot_args(p: argparse.ArgumentParser) -> None:
    d = SimParams()
    p.add_argument("--speed", type=float, default=5000.0, help="stage speed cap, µm/s")
    p.add_argument("--acc", type=float, default=d.acc_um_s2, help="µm/s² (assumed)")
    p.add_argument(
        "--jerk", type=float, default=d.jerk_um_s3 / 1000, help="mm/s³, 0 = trapezoid (assumed)"
    )
    p.add_argument("--repeat", type=float, default=d.repeat_um, help="ISO repeatability, µm")
    p.add_argument("--flex-hz", type=float, default=d.flex_hz, help="arm first mode (assumed)")
    p.add_argument("--flex-zeta", type=float, default=d.flex_zeta)
    p.add_argument("--jitter", type=float, default=d.jitter_um, help="standstill RMS µm")
    p.add_argument("--exposure", type=float, default=0.002, help="s")
    p.add_argument("--latency", type=float, default=0.05, help="detect-to-command, s")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("table", help="speeds and magnifications for this robot")
    _robot_args(t)
    t.add_argument("--coverslip", type=float, default=18.0, help="mm, square")
    r = sub.add_parser("run", help="simulate the stage under the camera")
    _robot_args(r)
    r.add_argument("--out", required=True)
    r.add_argument("--mode", choices=("hold", "scan", "follow", "zsweep"), default="follow")
    r.add_argument("--objective", choices=sorted(VIEWS), default="10x")
    r.add_argument("--size", type=lambda s: _pair(s, int), help="render WxH (default half sensor)")
    r.add_argument("--world", type=_pair, help="slide patch WxH, µm (default: sized to the view)")
    r.add_argument("--cast", help="ecosim cast for a 2.9x2.2 mm frame; scaled to --world")
    r.add_argument("--target", default="paramecium", help="follow: species to follow")
    r.add_argument("--kp", type=float, default=4.0, help="follow: 1/s")
    r.add_argument("--deadband", type=float, default=10.0, help="follow: px")
    r.add_argument("--tiles", type=lambda s: _pair(s, int), default=(3, 2), help="scan: NxM")
    r.add_argument("--dwell", type=float, default=0.3, help="scan: s per tile once settled")
    r.add_argument("--zrate", type=float, default=100.0, help="zsweep: µm/s")
    r.add_argument("--depth", type=float, default=150.0, help="chamber depth, µm")
    r.add_argument("--focus", type=float, help="µm above floor (default depth/2)")
    r.add_argument("--chamber", choices=("sealed", "well"), default="sealed")
    r.add_argument("--well-depth", type=float, default=1000.0, help="well: µm of water")
    r.add_argument("--frames", type=int, default=300)
    r.add_argument("--fps", type=float, default=60.0)
    r.add_argument("--polarity", choices=("darkfield", "brightfield"), default="darkfield")
    r.add_argument("--noise", type=float, default=4.0)
    r.add_argument("--seed", type=int, default=0)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    bad = (
        a.speed <= 0
        or a.acc <= 0
        or not 0 < a.exposure < 1
        or a.latency < 0
        or (
            a.cmd == "run"
            and (a.frames < 1 or a.fps <= 0 or a.depth <= 0 or min(a.world or (1, 1)) <= 0)
        )
    )
    if bad:
        print("stagesim: speed, acc, exposure, fps, depth, world must be > 0", file=sys.stderr)
        return 2
    if a.cmd == "table":
        try:
            params = SimParams(
                speed_um_s=a.speed,
                acc_um_s2=a.acc,
                jerk_um_s3=a.jerk * 1000,
                repeat_um=a.repeat,
                flex_hz=a.flex_hz,
                flex_zeta=a.flex_zeta,
                jitter_um=a.jitter,
            )
        except ValueError as e:
            print(f"stagesim: {e}", file=sys.stderr)
            return 2
        print(table(params, a.exposure, a.latency, a.coverslip))
        return 0
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
