"""stage.py: the view <-> robot frame, the wire protocol, and the sim's physics.

The wire tests talk to a local TCP emulator of the Meca500's text API, built
from the codes in mecademicpy. It is not the robot: ``scripts/meca-smoke.sh``
is the check against the real one.
"""

from __future__ import annotations

import math
import socket
import threading

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stage import (
    MecaError,
    MecaStage,
    SimParams,
    SimStage,
    SlideFrame,
    StageLimitError,
    calibrate_xy,
    move_time,
    repeatability_sigma,
)

finite = st.floats(-5000, 5000, allow_nan=False)


# ---- frame --------------------------------------------------------------------
@given(finite, finite, st.floats(-20, 250), st.floats(-180, 180), st.sampled_from([-1.0, 1.0]))
def test_frame_round_trip(x, y, z, yaw, zs):
    f = SlideFrame(yaw_deg=yaw, z_sign=zs)
    back = f.from_wrf(f.to_wrf((x, y, z)))
    assert np.allclose(back, (x, y, z), atol=1e-6)


def test_view_moves_slide_the_other_way():
    f = SlideFrame(origin_mm=(200, 0, 120), yaw_deg=0, z_sign=-1)
    x, y, z, *_ = f.to_wrf((1000, 0, 50))
    assert (x, y) == pytest.approx((199.0, 0.0))  # look +1 mm -> slide -1 mm
    assert z == pytest.approx(120 - 0.05)  # focus up 50 µm -> slide away from objective


@pytest.mark.parametrize(
    "view", [(0, 0, 251), (0, 0, -21), (9001, 0, 0), (math.nan, 0, 0), (0, math.inf, 0)]
)
def test_limits_reject(view):
    with pytest.raises(StageLimitError):
        SlideFrame().check(view)


def test_frame_rejects_bad_config():
    with pytest.raises(ValueError):
        SlideFrame(z_sign=0.5)
    with pytest.raises(ValueError):
        SlideFrame(limits_um=((0, 0), (0, 1), (0, 1)))


# ---- calibration --------------------------------------------------------------
@settings(max_examples=50, deadline=None)
@given(st.floats(-179, 179), st.floats(0.1, 10), st.booleans(), st.integers(0, 2**31))
def test_calibrate_recovers_yaw_scale_mirror(yaw, upp, mirrored, seed):
    rng = np.random.default_rng(seed)
    moves = rng.uniform(-500, 500, (6, 2))
    moves[0], moves[1] = (300, 0), (0, 300)  # span both axes
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    shifts = moves @ np.array([[c, s], [-s, c]]) / upp  # rows: R m / upp
    if mirrored:
        shifts = shifts * [1, -1]
    shifts += rng.normal(0, 0.2, shifts.shape)  # half-pixel-ish tracking noise
    y, u, m = calibrate_xy(moves, shifts)
    assert m == mirrored
    assert u == pytest.approx(upp, rel=0.02)
    assert abs((y - yaw + 180) % 360 - 180) < 1.0


@pytest.mark.parametrize(
    "moves, shifts",
    [
        (np.zeros((3, 2)), np.ones((3, 2))),  # no motion
        (np.array([[1, 0], [2, 0]]), np.array([[1, 0], [2, 0]])),  # one direction only
        (np.ones((3, 2)), np.ones((2, 2))),  # shape mismatch
        (np.array([[1, 0], [0, math.nan]]), np.ones((2, 2))),
    ],
)
def test_calibrate_rejects_degenerate(moves, shifts):
    with pytest.raises(ValueError):
        calibrate_xy(moves, shifts)


# ---- sim physics --------------------------------------------------------------
def _quiet(**kw) -> SimParams:
    return SimParams(**{"jitter_um": 0.0, "repeat_um": 0.0, "jerk_um_s3": 0.0, **kw})


@pytest.mark.parametrize("dist", [20.0, 400.0, 3000.0])
def test_sim_move_time_matches_trapezoid(dist):
    p = _quiet(speed_um_s=1000, acc_um_s2=20_000)
    s = SimStage(params=p)
    s.move_to(dist, 0, 0)
    while s.moving:
        s.step(0.001)
    assert s.t == pytest.approx(move_time(dist, 1000, 20_000), abs=0.004)
    assert s.cmd == pytest.approx([dist, 0, 0])


def test_sim_never_exceeds_speed_or_accel():
    p = _quiet(speed_um_s=800, acc_um_s2=10_000)
    s = SimStage(params=p)
    for target in [(1000, 500, 0), (-300, 0, 100), (0, 0, 0)]:
        s.move_to(*target)
    v_prev = np.zeros(3)
    while s.moving:
        s.step(p.substep_s)
        assert np.linalg.norm(s.vel) <= 800 + 1e-6
        # 20% slack for the arrival substep's discretization, no more
        assert np.linalg.norm(s.vel - v_prev) <= 1.2 * 10_000 * p.substep_s
        v_prev = s.vel.copy()


def test_sim_rings_after_a_stop_then_settles():
    s = SimStage(params=_quiet(speed_um_s=5000, acc_um_s2=100_000, flex_hz=20, flex_zeta=0.05))
    s.move_to(2000, 0, 0)
    while s.moving:
        s.step(0.001)
    assert s.ringing_um > 1.0  # decel = 100 mm/s² on a 20 Hz mode: a/w² ≈ 6 µm
    assert not s.idle
    s.wait_idle()
    assert s.ringing_um < 0.1
    assert s.pose() == pytest.approx((2000, 0, 0), abs=0.1)


def test_sim_jerk_limit_holds_and_costs_acc_over_jerk():
    p = _quiet(speed_um_s=2000, acc_um_s2=50_000, jerk_um_s3=1e6)
    s = SimStage(params=p)
    s.move_to(1500, 0, 0)
    a_prev = np.zeros(3)
    peak_a = 0.0
    while s.moving:
        s.step(p.substep_s)
        assert np.linalg.norm(s.acc - a_prev) <= 1e6 * p.substep_s * 1.01 + 1e-6
        peak_a = max(peak_a, float(np.linalg.norm(s.acc)))
        a_prev = s.acc.copy()
    assert peak_a <= 50_000 * 1.01
    assert s.t == pytest.approx(move_time(1500, 2000, 50_000, 1e6), abs=0.003)
    assert s.cmd == pytest.approx([1500, 0, 0])


def test_sim_jerk_limit_cuts_ringing():
    def ring(jerk):
        s = SimStage(params=_quiet(speed_um_s=5000, acc_um_s2=100_000, jerk_um_s3=jerk))
        s.move_to(2000, 0, 0)
        while s.moving:
            s.step(0.001)
        return s.ringing_um

    # a 50 ms ramp against a 40 ms flex period: the step that rings the mode is gone
    assert ring(2e6) < ring(0) / 5


@settings(max_examples=30, deadline=None)
@given(st.lists(st.floats(0.0001, 0.05), min_size=5, max_size=60))
def test_sim_path_is_continuous_whatever_the_step_sizes(dts):
    """Uneven step() calls (a camera loop's dt, wait_idle's) never make the path jump."""
    p = _quiet(speed_um_s=3000, acc_um_s2=50_000, jerk_um_s3=1e6)
    s = SimStage(params=p)
    s.move_to(800, -300, 20)
    prev, t_prev = s.cmd.copy(), s.t
    for dt in dts:
        s.step(dt)
        assert np.linalg.norm(s.cmd - prev) <= 3000 * (s.t - t_prev) + 1e-6
        prev, t_prev = s.cmd.copy(), s.t


def test_sim_repeatability_scatter_matches_spec():
    """Returning to one point many times: ISO 9283 RP from the scatter ≈ 5 µm."""
    s = SimStage(params=SimParams(jitter_um=0.0, acc_um_s2=200_000, speed_um_s=5000), seed=3)
    pts = []
    for i in range(400):
        s.move_to(500.0 * (i % 2), 0, 0)
        s.wait_idle()
        if i % 2 == 0:
            pts.append(s.pose())
    pts = np.array(pts)
    dist = np.linalg.norm(pts - pts.mean(0), axis=1)
    rp = dist.mean() + 3 * dist.std()
    assert rp == pytest.approx(5.0, rel=0.15)
    assert repeatability_sigma(5.0) == pytest.approx(1.383, abs=0.01)


def test_sim_jog_stops_at_the_soft_limit():
    f = SlideFrame(limits_um=((-100, 100), (-100, 100), (0, 50)))
    s = SimStage(frame=f, params=_quiet(acc_um_s2=1e6))
    s.jog(2000, 0, 0)
    for _ in range(200):
        s.step(0.005)
    assert s.cmd[0] <= 100
    assert not s.moving


def test_sim_rejects_bad_input():
    s = SimStage()
    with pytest.raises(StageLimitError):
        s.move_to(0, 0, 10_000)
    assert not s.queue
    with pytest.raises(ValueError):
        s.jog(1e9, 0, 0)
    with pytest.raises(ValueError):
        s.jog(math.nan, 0, 0)
    with pytest.raises(ValueError):
        s.set_speed(0)
    with pytest.raises(ValueError):
        s.step(-1)
    with pytest.raises(ValueError):
        SimParams(acc_um_s2=0)
    with pytest.raises(ValueError):
        SimParams(substep_s=0.1)  # coarser than the flex mode can be integrated


def test_sim_is_deterministic_for_a_seed():
    def path(seed):
        s = SimStage(seed=seed)
        s.move_to(300, 200, 10)
        out = []
        for _ in range(50):
            s.step(1 / 60)
            out.append(s.pose())
        return out

    assert path(7) == path(7)
    assert path(7) != path(8)


# ---- the wire, against an emulator ---------------------------------------------
class FakeMeca:
    """Speaks enough of the Meca500 text API: welcome, motion commands
    queue silently, GetPose replies with the last MoveLin, checkpoints reply
    3030, anything in ``fail`` replies with that error code."""

    def __init__(self, welcome: str = "[3000][Connected to Meca500]") -> None:
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.port = self.srv.getsockname()[1]
        self.got: list[str] = []
        self.fail: dict[str, str] = {}
        self.pose = "200.0,0.0,120.0,0.0,90.0,0.0"
        self.welcome = welcome
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    def _serve(self) -> None:
        try:
            self._session()
        except OSError:  # the client hung up mid-reply, or the test closed the server
            return

    def _session(self) -> None:
        conn, _ = self.srv.accept()
        with conn:
            conn.sendall(self.welcome.encode() + b"\0")
            buf = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
                while b"\0" in buf:
                    raw, buf = buf.split(b"\0", 1)
                    cmd = raw.decode()
                    self.got.append(cmd)
                    name = cmd.split("(")[0]
                    if name in self.fail:
                        conn.sendall(f"{self.fail[name]}\0".encode())
                    elif name == "MoveLin":
                        self.pose = cmd[len("MoveLin(") : -1]
                    elif name == "GetPose":
                        conn.sendall(f"[2027][{self.pose}]\0".encode())
                    elif name == "SetCheckpoint":
                        n = cmd[len("SetCheckpoint(") : -1]
                        conn.sendall(f"[3004][]\0[3030][{n}]\0".encode())
                    elif name == "ActivateRobot":
                        conn.sendall(b"[2000][Motors activated.]\0")
                    elif name == "ClearMotion":
                        conn.sendall(b"[2044][The motion was cleared.]\0")

    def close(self) -> None:
        self.srv.close()


@pytest.fixture
def meca():
    fake = FakeMeca()
    yield fake
    fake.close()


def test_wire_move_and_pose(meca):
    f = SlideFrame(origin_mm=(200, 0, 120), z_sign=-1)
    st_ = MecaStage("127.0.0.1", f, port=meca.port, timeout=5, speed_um_s=2000)
    st_.start()
    st_.move_to(1000, -500, 40)
    st_.wait_idle()
    assert st_.pose() == pytest.approx((1000, -500, 40), abs=0.1)
    st_.close()
    assert meca.got[0] == "SetCartLinVel(2.0000)"
    assert meca.got[1] == "ActivateRobot"
    assert meca.got[2] == "MoveLin(199.0000,0.5000,119.9600,0.0000,90.0000,0.0000)"
    assert meca.got[3] == "SetCheckpoint(1)"


def test_wire_out_of_limits_sends_nothing(meca):
    st_ = MecaStage("127.0.0.1", SlideFrame(), port=meca.port, timeout=5)
    with pytest.raises(StageLimitError):
        st_.move_to(0, 0, 5000)  # 5 mm into the objective
    with pytest.raises(ValueError):
        st_.jog(0, 0, 1e9)
    with pytest.raises(ValueError):
        st_.set_speed(-1)
    st_.move_to(0, 0, 0)
    st_.wait_idle()
    st_.close()
    # wait_idle's checkpoint reply means the emulator has logged everything sent before it
    assert [c.split("(")[0] for c in meca.got] == ["SetCartLinVel", "MoveLin", "SetCheckpoint"]


def test_wire_error_code_raises(meca):
    meca.fail["MoveLin"] = "[1011][The robot is in error.]"
    st_ = MecaStage("127.0.0.1", SlideFrame(), port=meca.port, timeout=5)
    st_.move_to(0, 0, 0)
    with pytest.raises(MecaError) as e:
        st_.wait_idle()
    assert e.value.code == 1011
    st_.close()


def test_wire_bad_pose_reply_raises(meca):
    meca.fail["GetPose"] = "[2027][1,2,three]"
    st_ = MecaStage("127.0.0.1", SlideFrame(), port=meca.port, timeout=5)
    with pytest.raises(MecaError):
        st_.pose()
    st_.close()


def test_wire_jog_is_view_velocity_in_wrf(meca):
    st_ = MecaStage("127.0.0.1", SlideFrame(yaw_deg=90), port=meca.port, timeout=5)
    st_.jog(1000, 0, 0)
    st_.stop()
    st_.close()
    jog = next(c for c in meca.got if c.startswith("MoveLinVelWrf"))
    vals = [float(v) for v in jog[len("MoveLinVelWrf(") : -1].split(",")]
    # yaw 90: view +x is WRF +y; the slide moves the other way, 1 mm/s
    assert vals == pytest.approx([0, -1, 0, 0, 0, 0], abs=1e-6)


def test_wire_second_user_refused():
    fake = FakeMeca(welcome="[3001][Another user is already connected, closing connection.]")
    with pytest.raises(MecaError) as e:
        MecaStage("127.0.0.1", SlideFrame(), port=fake.port, timeout=5)
    assert e.value.code == 3001
    fake.close()


def test_wire_garbage_reply_raises():
    fake = FakeMeca(welcome="hello")
    with pytest.raises(MecaError):
        MecaStage("127.0.0.1", SlideFrame(), port=fake.port, timeout=5)
    fake.close()
