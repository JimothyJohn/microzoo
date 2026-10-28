"""optics.py against the physics it claims: the Airy ring where 0.61 λ/NA puts it,
energy kept, ±dz symmetry, a defocus OTF with a zero inside the passband (the
thing a Gaussian never has), depth of field scaling as λn/NA², and a defocus
disc of radius dz·tan(asin(NA/n))."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from optics import MAX_HALF_PX, MEDIA, Optics, _quantise, mtf, psf

X10 = Optics(0.25)
OIL100 = Optics(1.25, n=MEDIA["oil"])


def _radial(k: np.ndarray) -> np.ndarray:
    c = k.shape[0] // 2
    return k[c, c:]


def _encircled_radius(k: np.ndarray, frac: float) -> float:
    """Radius in px holding ``frac`` of the kernel's light."""
    c = k.shape[0] // 2
    y, x = np.indices(k.shape)
    r = np.hypot(x - c, y - c).ravel()
    order = np.argsort(r)
    cum = np.cumsum(k.ravel()[order])
    return float(r[order][np.searchsorted(cum, frac * cum[-1])])


@pytest.mark.parametrize("optics", [Optics(0.10), X10, OIL100], ids=["4x", "10x", "100x-oil"])
def test_in_focus_psf_is_airy(optics):
    px = optics.airy_um / 12  # fine sampling: 12 px to the first dark ring
    prof = _radial(psf(optics, 0.0, px))
    first_min = int(np.argmax(np.diff(prof) > 0))  # where the profile turns back up
    assert first_min * px == pytest.approx(optics.airy_um, rel=0.1)
    assert prof[first_min] < 0.02 * prof[0]  # a real dark ring, not a shoulder
    assert prof[first_min + 1 : first_min + 12].max() > 3 * prof[first_min]  # then a bright one


@pytest.mark.parametrize("dz", [0.0, 3.0, 20.0])
def test_light_is_kept_and_kernel_is_odd_square(dz):
    k = psf(X10, dz, 0.6)
    assert k.ndim == 2 and k.shape[0] == k.shape[1] and k.shape[0] % 2 == 1
    assert 0.97 < k.sum() <= 1.0 + 1e-6
    assert (k >= 0).all()
    assert np.allclose(k, k[::-1, ::-1], atol=1e-7)  # point-symmetric: no aberrations


def test_psf_is_symmetric_in_dz():
    assert np.array_equal(psf(X10, 12.0, 0.6), psf(X10, -12.0, 0.6))


def test_defocus_otf_has_a_zero_then_rebounds():
    """The signature a Gaussian blur cannot fake: the MTF falls to ~0 inside the
    passband and comes back up. Detail at that frequency is gone, not just weak."""
    px = 0.3
    m_focus = mtf(psf(X10, 0.0, px))
    m = mtf(psf(X10, 3 * X10.dof_um, px))
    n = len(m) - 1  # bin n is Nyquist, 1 / (2 px)
    cutoff_bin = int(n * (2 * X10.na / X10.wavelength_um) / (1 / (2 * px)))
    band = m[1:cutoff_bin]
    dip = int(np.argmin(band[: len(band) // 2])) + 1
    assert m[dip] < 0.01
    assert m[dip:cutoff_bin].max() > 5 * m[dip]  # rebound past the zero
    assert m_focus[dip] > 0.3  # in focus that frequency is well transmitted
    assert np.all(np.diff(m_focus[1:cutoff_bin]) < 1e-3)  # in focus: no dips, falls to cutoff


@pytest.mark.parametrize("optics", [X10, OIL100], ids=["10x", "100x-oil"])
def test_depth_of_field_scales_as_lambda_n_over_na_squared(optics):
    px = optics.airy_um / 6
    peak0 = psf(optics, 0.0, px).max()
    assert psf(optics, 0.25 * optics.dof_um, px).max() > 0.8 * peak0  # inside the DoF
    assert psf(optics, 3 * optics.dof_um, px).max() < 0.2 * peak0  # well outside it


def test_oil_100x_dof_is_half_a_micron():
    assert OIL100.dof_um == pytest.approx(0.53, abs=0.01)
    assert X10.dof_um == pytest.approx(8.8)


@pytest.mark.parametrize("optics", [X10, OIL100], ids=["10x", "100x-oil"])
def test_far_defocus_is_a_disc_of_the_geometric_radius(optics):
    """Far out of focus the PSF is the pupil's shadow: light uniform in sin(θ) up to
    NA/n, landing at dz·tan(θ). So 85% of it sits inside dz·tan(asin(√0.85·NA/n)),
    which at NA 1.25 oil is well short of the rim (tan stretches the steep rays)."""
    dz = 15 * optics.dof_um
    px = optics.blur_radius_um(dz) / 30
    r = _encircled_radius(psf(optics, dz, px), 0.85) * px
    expect = dz * math.tan(math.asin(math.sqrt(0.85) * optics.na / optics.n))
    assert r == pytest.approx(expect, rel=0.1)
    assert r < optics.blur_radius_um(dz)


def test_huge_defocus_is_capped_and_drops_light_rather_than_concentrating_it():
    k = psf(OIL100, 50.0, 0.06)
    assert k.shape[0] == 2 * MAX_HALF_PX + 1
    assert k.sum() < 0.9


@pytest.mark.parametrize(
    "kw", [dict(na=0.0), dict(na=-0.1), dict(na=1.0), dict(na=1.6, n=1.515), dict(wavelength_um=0)]
)
def test_optics_rejects_unphysical(kw):
    with pytest.raises(ValueError):
        Optics(**kw)


def test_psf_rejects_bad_scale():
    with pytest.raises(ValueError):
        psf(X10, 0.0, 0.0)


def test_quantise_is_monotone_and_close():
    zs = np.linspace(0, 150, 3001)
    q = [_quantise(X10, z) for z in zs]
    assert all(b >= a for a, b in zip(q, q[1:], strict=False))
    for z, qz in zip(zs, q, strict=True):
        assert abs(qz - z) <= max(X10.z_step_um() / 2, 0.016 * z) + 1e-9


@settings(max_examples=40, deadline=None)
@given(
    na=st.floats(0.02, 1.4),
    immersion=st.sampled_from(sorted(MEDIA)),
    px=st.floats(0.05, 8.0),
    dz=st.floats(-200, 200),
)
def test_any_valid_objective_gives_a_sane_kernel(na, immersion, px, dz):
    n = MEDIA[immersion]
    if na >= n:
        with pytest.raises(ValueError):
            Optics(na, n=n)
        return
    k = psf(Optics(na, n=n), dz, px)
    assert np.isfinite(k).all() and (k >= 0).all()
    assert k.shape[0] % 2 == 1 and k.shape[0] <= 2 * MAX_HALF_PX + 1
    assert k.sum() <= 1.0 + 1e-5
    assert math.isfinite(float(k.max()))
