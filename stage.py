#!/usr/bin/env python3
"""stage.py: the slide held by a Meca500, as a three-axis microscope stage.

One interface, two implementations:

    MecaStage   the real robot over its text API (TCP 10000, null-terminated
                ASCII, replies ``[code][data]``). Stdlib socket only, so it
                runs on the Pi next to the capture loop.
    SimStage    the same calls against a time-stepped model: trapezoidal
                moves at the set speed and acceleration, the arm's first flex
                mode ringing after every acceleration change, ISO 9283
                repeatability scatter at each move's end, and servo jitter.

Coordinates are the *view*, in µm, not the robot: ``(x, y)`` is the point on
the slide under the optical axis and ``z`` is the focal plane's height above
the chamber floor. ``SlideFrame`` maps a view to the robot's world frame
(WRF, mm and degrees): looking at +x means the slide moves -x under the
objective, and raising focus means the slide moves away from the objective
(``z_sign`` says which WRF z direction that is for this mounting).
Calibrate XY once per mounting with ``calibrate_xy`` (robot moves in, image
shifts out); set ``origin_mm`` by jogging to the reference mark with the
chamber floor in focus and reading ``raw_pose``.

Every move is checked against the frame's soft limits *before* a byte goes to
the robot: the Z limit is what keeps the slide off the objective.

Spec numbers (Meca500 R3 user manual): 5 µm repeatability, 0.5 kg payload,
330 mm reach at the flange. Protocol codes are from Mecademic's mecademicpy
(``mx_robot_def.py``). The sim's acceleration, flex mode and jitter are
*assumptions* until measured on the rig; they are the knobs to replace.

    python stage.py --host 192.168.0.100 pose
    python stage.py --host 192.168.0.100 smoke   # +-100 µm square in XY, no Z
"""

from __future__ import annotations

import argparse
import math
import socket
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

__all__ = [
    "MecaError",
    "MecaStage",
    "SimParams",
    "SimStage",
    "SlideFrame",
    "Stage",
    "StageLimitError",
    "calibrate_xy",
    "move_time",
    "repeatability_sigma",
]

MECA_PORT = 10000
MECA_REPEATABILITY_UM = 5.0
MAX_SPEED_UM_S = 20_000.0  # a slide over an objective; the arm can do far more
# Status codes, from mecademicpy's MxRobotStatusCode.
ST_ACTIVATED = 2000
ST_HOME_DONE = 2002
ST_GET_POSE = 2027
ST_CLEAR_MOTION = 2044
ST_CONNECTED = 3000
ST_CHECKPOINT = 3030
# Every 1xxx code is a command error; these 3xxx codes are errors too.
ST_ERRORS_3XXX = frozenset(
    {3001, 3003, 3005, 3006, 3009, 3014, 3017, 3020, 3023, 3024, 3025, 3026, 3027, 3029}
    | {3031, 3033, 3037, 3039, 3041, 3042, 3043, 3044, 3046, 3047, 3049, 3050, 3051, 3052}
)

View = tuple[float, float, float]


class StageLimitError(ValueError):
    """A move would leave the soft limits; nothing was sent."""


class MecaError(RuntimeError):
    def __init__(self, code: int, data: str) -> None:
        super().__init__(f"[{code}][{data}]")
        self.code = code
        self.data = data


def is_error(code: int) -> bool:
    return 1000 <= code < 2000 or code in ST_ERRORS_3XXX


def repeatability_sigma(rp_um: float) -> float:
    """Per-axis sigma whose 3D scatter has ISO 9283 RP = mean + 3 std of the
    distance from the mean pose. For an isotropic 3D Gaussian that distance is
    Maxwell-distributed: mean 1.596 sigma, std 0.673 sigma, RP = 3.615 sigma."""
    return rp_um / (2 * math.sqrt(2 / math.pi) + 3 * math.sqrt(3 - 8 / math.pi))


@dataclass(frozen=True)
class SlideFrame:
    """Where the view sits in the robot's WRF.

    ``origin_mm``: WRF position of the flange (TRF) when the view is (0, 0, 0),
    i.e. reference mark centred, chamber floor in focus. ``yaw_deg``: the
    slide's x axis turned from WRF x about WRF z. ``z_sign``: the WRF z
    direction that takes the slide *away* from the objective. ``orient_deg``:
    the gripper's fixed orientation for every move. ``limits_um``: the view's
    soft box, ((x0, x1), (y0, y1), (z0, z1)).
    """

    origin_mm: tuple[float, float, float] = (200.0, 0.0, 120.0)
    yaw_deg: float = 0.0
    z_sign: float = -1.0
    orient_deg: tuple[float, float, float] = (0.0, 90.0, 0.0)
    limits_um: tuple[tuple[float, float], ...] = ((-9000, 9000), (-9000, 9000), (-20, 250))

    def __post_init__(self) -> None:
        if self.z_sign not in (-1.0, 1.0):
            raise ValueError("z_sign must be +1 or -1")
        if len(self.limits_um) != 3 or any(not lo < hi for lo, hi in self.limits_um):
            raise ValueError("limits_um: three (lo, hi) pairs with lo < hi")

    def check(self, view: View) -> None:
        for v, (lo, hi), ax in zip(view, self.limits_um, "xyz", strict=True):
            if not (math.isfinite(v) and lo <= v <= hi):
                raise StageLimitError(f"{ax}={v} µm outside [{lo}, {hi}]")

    def to_wrf(self, view: View) -> tuple[float, float, float, float, float, float]:
        """View (µm) -> flange pose in the WRF: x, y, z (mm), alpha, beta, gamma (deg)."""
        c, s = math.cos(math.radians(self.yaw_deg)), math.sin(math.radians(self.yaw_deg))
        x, y, z = view
        ox, oy, oz = self.origin_mm
        a, b, g = self.orient_deg
        # the slide moves opposite to where the view goes
        return (
            ox - (c * x - s * y) / 1000,
            oy - (s * x + c * y) / 1000,
            oz + self.z_sign * z / 1000,
            a,
            b,
            g,
        )

    def from_wrf(self, pose: tuple[float, ...]) -> View:
        c, s = math.cos(math.radians(self.yaw_deg)), math.sin(math.radians(self.yaw_deg))
        ox, oy, oz = self.origin_mm
        dx, dy = (ox - pose[0]) * 1000, (oy - pose[1]) * 1000
        return (c * dx + s * dy, -s * dx + c * dy, self.z_sign * (pose[2] - oz) * 1000)


def calibrate_xy(moves_um: np.ndarray, shifts_px: np.ndarray) -> tuple[float, float, bool]:
    """Fit image shift = k * R(theta) * M * robot move, M = identity or a y mirror.

    ``moves_um``: (n, 2) WRF XY moves of the flange; ``shifts_px``: (n, 2)
    image shifts measured for each (track one debris particle across the
    moves). Returns (yaw_deg, um_per_px, mirrored). Image rows run down while
    WRF y runs up, so ``mirrored`` is the common answer; the fit picks
    whichever handedness leaves the smaller residual.
    """
    m = np.asarray(moves_um, float)
    p = np.asarray(shifts_px, float)
    if m.shape != p.shape or m.ndim != 2 or m.shape[1] != 2 or len(m) < 2:
        raise ValueError("need (n, 2) moves and shifts with n >= 2")
    if np.linalg.matrix_rank(m) < 2 or not np.all(np.isfinite(m)) or not np.all(np.isfinite(p)):
        raise ValueError("moves must be finite and span two directions")
    best: tuple[float, float, float, bool] | None = None
    for mirrored in (False, True):
        q = p * [1.0, -1.0] if mirrored else p
        mc, qc = m[:, 0] + 1j * m[:, 1], q[:, 0] + 1j * q[:, 1]
        k = np.vdot(mc, qc) / np.vdot(mc, mc)  # complex LSQ: q = k m, k = (1/um_per_px) e^{i yaw}
        resid = float(np.sum(np.abs(qc - k * mc) ** 2))
        if best is None or resid < best[0]:
            best = (resid, float(np.degrees(np.angle(k))), float(1 / abs(k)), mirrored)
    assert best is not None
    return best[1], best[2], best[3]


def move_time(dist_um: float, speed_um_s: float, acc_um_s2: float) -> float:
    """Rest-to-rest straight-line move time, trapezoid or triangle profile."""
    if dist_um <= 0:
        return 0.0
    if dist_um <= speed_um_s**2 / acc_um_s2:
        return 2 * math.sqrt(dist_um / acc_um_s2)
    return dist_um / speed_um_s + speed_um_s / acc_um_s2


class Stage(Protocol):
    """What capture, focus and follow code may ask of the stage."""

    frame: SlideFrame

    def pose(self) -> View: ...
    def move_to(self, x: float, y: float, z: float) -> None: ...
    def jog(self, vx: float, vy: float, vz: float) -> None: ...
    def stop(self) -> None: ...
    def set_speed(self, um_s: float) -> None: ...
    def wait_idle(self) -> None: ...


def _check_speed(um_s: float) -> float:
    if not (math.isfinite(um_s) and 0 < um_s <= MAX_SPEED_UM_S):
        raise ValueError(f"speed must be in (0, {MAX_SPEED_UM_S:g}] µm/s, got {um_s}")
    return um_s


def _check_jog(v: tuple[float, float, float]) -> None:
    if not all(math.isfinite(c) for c in v) or math.hypot(*v) > MAX_SPEED_UM_S:
        raise ValueError(f"jog must be finite and at most {MAX_SPEED_UM_S:g} µm/s")


def _args(vals: tuple[float, ...]) -> str:
    return ",".join(f"{v:.4f}" for v in vals)


class MecaStage:
    """The real robot. The robot allows one control connection at a time.

    Assumes it is already holding the slide at a safe pose; ``start`` activates
    and homes only when asked, since homing swings every joint. Moves are
    MoveLin in the WRF at the frame's fixed orientation; ``wait_idle`` sends a
    checkpoint and returns once everything queued before it has finished.
    """

    def __init__(
        self,
        host: str,
        frame: SlideFrame,
        port: int = MECA_PORT,
        timeout: float = 30.0,
        speed_um_s: float = 1000.0,
    ) -> None:
        self.frame = frame
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._buf = b""
        self._checkpoint = 0
        try:
            code, data = self._read()
            if code != ST_CONNECTED:
                raise MecaError(code, data)
            self.set_speed(speed_um_s)
        except BaseException:
            self._sock.close()
            raise

    # ---- wire ------------------------------------------------------------
    def send(self, cmd: str) -> None:
        self._sock.sendall(cmd.encode("ascii") + b"\0")

    def _read(self) -> tuple[int, str]:
        while b"\0" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("robot closed the connection")
            self._buf += chunk
        raw, self._buf = self._buf.split(b"\0", 1)
        msg = raw.decode("ascii", "replace").strip()
        code_s, sep, rest = msg[1:].partition("]")
        if not msg.startswith("[") or not sep or not code_s.isdigit():
            raise MecaError(-1, msg)
        data = rest[1:-1] if rest.startswith("[") and rest.endswith("]") else rest
        return int(code_s), data

    def expect(self, *codes: int) -> tuple[int, str]:
        """Read until one of ``codes``; raise on any error code on the way."""
        while True:
            code, data = self._read()
            if is_error(code):
                raise MecaError(code, data)
            if code in codes:
                return code, data

    # ---- Stage -----------------------------------------------------------
    def start(self, home: bool = False) -> None:
        self.send("ActivateRobot")
        self.expect(ST_ACTIVATED)
        if home:
            self.send("Home")
            self.expect(ST_HOME_DONE)

    def raw_pose(self) -> tuple[float, ...]:
        """GetPose: the robot's target pose in the WRF (commanded, not encoders)."""
        self.send("GetPose")
        _, data = self.expect(ST_GET_POSE)
        try:
            vals = tuple(float(v) for v in data.split(","))
        except ValueError:
            raise MecaError(ST_GET_POSE, data) from None
        if len(vals) != 6:
            raise MecaError(ST_GET_POSE, data)
        return vals

    def pose(self) -> View:
        return self.frame.from_wrf(self.raw_pose())

    def move_to(self, x: float, y: float, z: float) -> None:
        self.frame.check((x, y, z))
        self.send(f"MoveLin({_args(self.frame.to_wrf((x, y, z)))})")

    def jog(self, vx: float, vy: float, vz: float) -> None:
        """Velocity mode in view µm/s. The robot stops on its own after its
        velocity timeout unless the next jog arrives first. Soft limits are the
        caller's job here: check ``pose()`` against ``frame`` between jogs."""
        _check_jog((vx, vy, vz))
        o, w = self.frame.to_wrf((0.0, 0.0, 0.0)), self.frame.to_wrf((vx, vy, vz))
        self.send(f"MoveLinVelWrf({_args((w[0] - o[0], w[1] - o[1], w[2] - o[2], 0, 0, 0))})")

    def stop(self) -> None:
        self.send("ClearMotion")
        self.expect(ST_CLEAR_MOTION)

    def set_speed(self, um_s: float) -> None:
        self.send(f"SetCartLinVel({_check_speed(um_s) / 1000:.4f})")

    def set_acc_pct(self, pct: float) -> None:
        """SetCartAcc takes a percentage of the robot's maximum, not mm/s²."""
        if not (math.isfinite(pct) and 0 < pct <= 100):
            raise ValueError("acceleration percentage must be in (0, 100]")
        self.send(f"SetCartAcc({pct:.3f})")

    def wait_idle(self) -> None:
        self._checkpoint = self._checkpoint % 8000 + 1
        self.send(f"SetCheckpoint({self._checkpoint})")
        while self.expect(ST_CHECKPOINT)[1].strip() != str(self._checkpoint):
            pass

    def close(self) -> None:
        self._sock.close()


@dataclass
class SimParams:
    """The model's knobs. Speed and repeatability are the robot's numbers;
    acceleration, flex and jitter are guesses until measured on the rig."""

    speed_um_s: float = 1000.0
    acc_um_s2: float = 50_000.0  # 50 mm/s²: an assumed gentle SetCartAcc
    repeat_um: float = MECA_REPEATABILITY_UM
    flex_hz: float = 25.0  # arm + gripper + slide first mode, assumed
    flex_zeta: float = 0.05
    jitter_um: float = 0.3  # standstill servo dither, RMS per axis, assumed
    substep_s: float = 0.0005

    def __post_init__(self) -> None:
        _check_speed(self.speed_um_s)
        ok = (
            self.acc_um_s2 > 0
            and self.flex_hz > 0
            and 0 <= self.flex_zeta < 1
            and self.repeat_um >= 0
            and self.jitter_um >= 0
            and 0 < self.substep_s <= 0.1 / self.flex_hz
        )
        if not ok:
            raise ValueError(
                "need acc > 0, flex_hz > 0, 0 <= zeta < 1, repeat >= 0, jitter >= 0, "
                "and a substep under a tenth of the flex period"
            )


@dataclass
class SimStage:
    """Time-stepped model of the arm carrying the slide; ``step(dt)`` advances it.

    ``pose()`` is where the slide really is (what the camera sees);
    ``cmd`` is the ideal trajectory the controller asked for.
    """

    frame: SlideFrame = field(default_factory=SlideFrame)
    params: SimParams = field(default_factory=SimParams)
    seed: int = 0

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.t = 0.0
        self.cmd = np.zeros(3)
        self.vel = np.zeros(3)
        self.acc = np.zeros(3)
        self.flex = np.zeros(3)  # first-mode deflection, driven by the commanded acceleration
        self.flex_v = np.zeros(3)
        self.err = np.zeros(3)  # repeatability offset, blends to a fresh draw over each move
        self.jitter = np.zeros(3)
        self._err_from = np.zeros(3)
        self._err_to = np.zeros(3)
        self._seg_len = 0.0
        self.queue: deque[np.ndarray] = deque()
        self.target: np.ndarray | None = None
        self.jog_v: np.ndarray | None = None
        self._sigma = repeatability_sigma(self.params.repeat_um)

    # ---- Stage -----------------------------------------------------------
    def pose(self) -> View:
        x, y, z = self.cmd + self.err + self.flex + self.jitter
        return float(x), float(y), float(z)

    def move_to(self, x: float, y: float, z: float) -> None:
        self.frame.check((x, y, z))
        if self.jog_v is not None:
            self.jog_v = np.zeros(3)  # a queued move waits for a jog to brake
        self.queue.append(np.array([x, y, z], float))

    def jog(self, vx: float, vy: float, vz: float) -> None:
        _check_jog((vx, vy, vz))
        self.queue.clear()
        self.target = None
        self.jog_v = np.array([vx, vy, vz], float)

    def stop(self) -> None:
        self.queue.clear()
        self.target = None
        self.jog_v = np.zeros(3)

    def set_speed(self, um_s: float) -> None:
        self.params.speed_um_s = _check_speed(um_s)

    def wait_idle(self, limit_s: float = 600.0) -> None:
        t0 = self.t
        while not self.idle:
            if self.t - t0 > limit_s:
                raise TimeoutError("sim stage never settled")
            self.step(0.005)

    # ---- model -----------------------------------------------------------
    @property
    def moving(self) -> bool:
        return self.target is not None or bool(self.queue) or bool(np.any(self.vel))

    @property
    def ringing_um(self) -> float:
        """Amplitude of the flex mode right now (deflection and velocity combined)."""
        w = 2 * math.pi * self.params.flex_hz
        return float(np.linalg.norm(np.hypot(self.flex, self.flex_v / w)))

    @property
    def idle(self) -> bool:
        """Stopped, and the flex mode has rung down to a tenth of a micron."""
        return not self.moving and self.ringing_um < 0.1

    def step(self, dt: float) -> None:
        if not (math.isfinite(dt) and dt > 0):
            raise ValueError("dt must be > 0")
        p = self.params
        n = max(1, math.ceil(dt / p.substep_s))
        h = dt / n
        w = 2 * math.pi * p.flex_hz
        for _ in range(n):
            v0 = self.vel.copy()
            self._advance(h)
            self.acc = (self.vel - v0) / h
            # base-excited mode: x'' + 2 zeta w x' + w^2 x = -a  (semi-implicit Euler)
            self.flex_v += h * (-self.acc - 2 * p.flex_zeta * w * self.flex_v - w * w * self.flex)
            self.flex += h * self.flex_v
            self.t += h
        self.jitter = self.rng.normal(0, p.jitter_um, 3) if p.jitter_um else np.zeros(3)

    def _accel_toward(self, v_want: np.ndarray, dv_max: float) -> float:
        dv = v_want - self.vel
        n = float(np.linalg.norm(dv))
        self.vel = self.vel + (dv if n <= dv_max else dv * (dv_max / n))
        return n

    def _advance(self, h: float) -> None:
        p = self.params
        dv_max = p.acc_um_s2 * h
        if self.target is None and self.queue and self.jog_v is None:
            self.target = self.queue.popleft()
            self._seg_len = float(np.linalg.norm(self.target - self.cmd))
            self._err_from = self.err.copy()
            self._err_to = self.rng.normal(0, self._sigma, 3)
        if self.target is not None:
            d = self.target - self.cmd
            dist = float(np.linalg.norm(d))
            # the fastest speed that can still stop in ``dist`` shedding dv_max per substep:
            # h (v²/2dv + v/2) = dist; the continuous limit is sqrt(2 a d)
            v_brake = (-dv_max + math.sqrt(dv_max**2 + 8 * p.acc_um_s2 * dist)) / 2
            v_cap = min(p.speed_um_s, v_brake, dist / h)  # dist/h: land on it, don't hop over
            v_want = v_cap * (d / dist) if dist > 0 else np.zeros(3)
            self._accel_toward(v_want, dv_max)
            if dist <= float(np.linalg.norm(self.vel)) * h + 1e-9:
                # pinned on the target; the last sliver of speed sheds next substep
                self.cmd = self.target.copy()
                self.err = self._err_to.copy()
                self.target = None
                return
            self.cmd = self.cmd + self.vel * h
            done = 1 - dist / self._seg_len if self._seg_len > 0 else 1.0
            self.err = self._err_from + (self._err_to - self._err_from) * done
        elif self.jog_v is not None:
            self._accel_toward(self.jog_v, dv_max)
            nxt = self.cmd + self.vel * h
            try:
                self.frame.check((float(nxt[0]), float(nxt[1]), float(nxt[2])))
            except StageLimitError:  # the real robot would fault on its work zone; stop dead
                self.vel = np.zeros(3)
                self.jog_v = None
                return
            self.cmd = nxt
            if not np.any(self.jog_v) and not np.any(self.vel):
                self.jog_v = None
        elif np.any(self.vel):
            self._accel_toward(np.zeros(3), dv_max)


# ---- CLI: read the pose, or a tiny square to prove the wiring ----------------
_OPEN = ((-1e6, 1e6), (-1e6, 1e6), (-1e6, 1e6))


def _smoke(st: MecaStage) -> int:
    x0, y0, z0 = st.pose()
    for dx, dy in ((100, 0), (100, 100), (0, 100), (0, 0)):
        st.move_to(x0 + dx, y0 + dy, z0)
        st.wait_idle()
        x, y, z = st.pose()
        print(f"asked ({dx:4d}, {dy:4d}) µm  got ({x - x0:8.2f}, {y - y0:8.2f}, {z - z0:6.2f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Meca500 slide stage: read pose or smoke-test XY.")
    ap.add_argument("action", choices=("pose", "smoke"))
    ap.add_argument("--host", default="192.168.0.100")
    ap.add_argument("--port", type=int, default=MECA_PORT)
    ap.add_argument("--speed", type=float, default=1000.0, help="µm/s for smoke moves")
    a = ap.parse_args(argv)
    try:
        _check_speed(a.speed)
        st = MecaStage(a.host, SlideFrame(limits_um=_OPEN), port=a.port, speed_um_s=a.speed)
    except ValueError as e:
        print(f"stage: {e}", file=sys.stderr)
        return 2
    except (OSError, MecaError) as e:
        print(f"stage: cannot connect to {a.host}:{a.port}: {e}", file=sys.stderr)
        return 2
    try:
        wrf = st.raw_pose()
        print("WRF pose: " + ", ".join(f"{v:.4f}" for v in wrf))
        if a.action == "smoke":
            # centre a frame on wherever the robot is, so the square is relative to here
            st.frame = SlideFrame(
                origin_mm=(wrf[0], wrf[1], wrf[2]), orient_deg=(wrf[3], wrf[4], wrf[5])
            )
            return _smoke(st)
        return 0
    except MecaError as e:
        print(f"stage: robot error {e}", file=sys.stderr)
        return 1
    finally:
        st.close()


if __name__ == "__main__":
    sys.exit(main())
