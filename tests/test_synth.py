"""The synthetic generator's contract: both illumination polarities render what
they claim, and the renderer rejects anything else."""

from __future__ import annotations

import numpy as np
import pytest

from synth import POLARITIES, render_frame, simulate, simulate_cross


def _frame(polarity):
    rng = np.random.default_rng(0)
    pos = np.array([[100.0, 60.0]])
    return render_frame(pos, (200, 120), 6.0, rng, polarity=polarity)[:, :, 0].astype(int)


def test_darkfield_is_bright_body_on_dark_field():
    f = _frame("darkfield")
    bg = np.median(f)
    assert bg < 40, bg
    assert f[60, 100] > bg + 120


def test_brightfield_is_dark_body_on_bright_field_with_lighter_core():
    f = _frame("brightfield")
    bg = np.median(f)
    assert bg > 200, bg
    rim = f[60, 100 + 5]  # along the long axis, inside the body but outside the core
    core = f[60, 100]
    assert rim < bg - 80, (rim, bg)
    assert core < bg - 30, (core, bg)
    assert core > rim, (core, rim)  # translucent: the centre is lighter than the rim


def test_both_polarities_have_the_same_contrast_magnitude_order():
    d, b = _frame("darkfield"), _frame("brightfield")
    assert abs(int(d[60, 100]) - np.median(d)) > 100
    assert abs(int(b[60, 100 + 5]) - np.median(b)) > 100


def test_unknown_polarity_is_rejected():
    with pytest.raises(ValueError, match="polarity"):
        _frame("phase")
    assert set(POLARITIES) == {"darkfield", "brightfield"}


def test_simulate_keeps_swimmers_inside_the_frame_and_apart_at_start():
    pos = simulate(8, 200, (320, 240), 4.0, seed=3, margin=12.0)
    assert pos.shape == (200, 8, 2)
    assert pos[..., 0].min() >= 12 and pos[..., 0].max() <= 320 - 12
    assert pos[..., 1].min() >= 12 and pos[..., 1].max() <= 240 - 12
    first = pos[0]
    d = np.linalg.norm(first[:, None] - first[None, :], axis=2)
    np.fill_diagonal(d, np.inf)
    assert d.min() >= 48


def test_simulate_is_seed_deterministic():
    a = simulate(5, 50, (320, 240), 3.0, seed=11)
    b = simulate(5, 50, (320, 240), 3.0, seed=11)
    c = simulate(5, 50, (320, 240), 3.0, seed=12)
    assert np.array_equal(a, b) and not np.array_equal(a, c)


def test_cross_paths_actually_cross_mid_clip():
    pos = simulate_cross(80, (320, 240), 2.5)
    d = np.linalg.norm(pos[:, 0] - pos[:, 1], axis=1)
    assert d.argmin() == 40 and d.min() < 1.0
    assert d[0] > 100 and d[-1] > 100
