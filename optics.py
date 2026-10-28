#!/usr/bin/env python3
"""optics.py: a wave-optics defocus PSF for ecosim, from the objective's numbers.

An aberration-free circular pupil of radius NA/λ, carrying the exact
angular-spectrum defocus phase 2π·dz·sqrt((n/λ)² − f²), Fourier-transformed to
an amplitude PSF and squared. In focus that is the Airy pattern (first dark ring
at 0.61 λ/NA); out of focus it is a ringed disc of radius ~dz·tan(asin(NA/n))
whose OTF has near-zeros inside the passband. Those zeros are the point: detail
lost there is gone, and no deconvolution or network gets it back without a prior.

Approximations, on purpose:
- Incoherent imaging (intensity PSF convolves intensity). Darkfield is really
  partially coherent scattering; that is second order next to the defocus itself.
- Scalar, no polarisation, no aberrations, no coverslip mismatch. At NA > 0.9
  vector effects widen the focus by a few percent.
- Pixels integrate: the PSF is computed on a grid fine enough for the band limit
  (λ/4NA) and box-binned to sensor pixels.
- Kernels are capped at ``MAX_HALF_PX`` px half-width; light beyond that is
  dropped, not renormalised. A body that far out of focus is a faint haze anyway.

Units are micrometres. Pure numpy (no scipy, per CLAUDE.md).

    python optics.py --na 0.25 --um-per-px 0.6 --dz 0 5 20 60
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

__all__ = ["MAX_HALF_PX", "MEDIA", "Optics", "mtf", "psf"]

MAX_HALF_PX = 256
WAVELENGTH_UM = 0.55  # green, the middle of a white LED
MEDIA = {"air": 1.0, "water": 1.33, "oil": 1.515}


@dataclass(frozen=True)
class Optics:
    """An objective and the medium it looks through. ``n`` is the immersion index."""

    na: float = 0.10
    wavelength_um: float = WAVELENGTH_UM
    n: float = 1.0

    def __post_init__(self) -> None:
        if not 0 < self.na < self.n:
            raise ValueError(f"need 0 < NA < n, got NA={self.na}, n={self.n}")
        if self.wavelength_um <= 0:
            raise ValueError(f"wavelength must be > 0, got {self.wavelength_um}")

    @property
    def dof_um(self) -> float:
        """Diffraction depth of field λn/NA² (the full width the focus holds)."""
        return self.wavelength_um * self.n / self.na**2

    @property
    def airy_um(self) -> float:
        """Radius of the first dark ring in focus, 0.61 λ/NA."""
        return 0.61 * self.wavelength_um / self.na

    def blur_radius_um(self, dz: float) -> float:
        """Geometric radius of the defocus disc ``dz`` µm from focus."""
        return abs(dz) * math.tan(math.asin(self.na / self.n))

    def z_step_um(self) -> float:
        """Defocus quantum near focus: an eighth of the DoF."""
        return self.dof_um / 8


Z_REL_STEP = 0.03  # far from focus the cache steps 3% of |dz|: a 3% wider disc is invisible
MAX_GRID = 2048  # FFT side cap; past it the fine grid coarsens (rings alias, pixels average them)


def _quantise(optics: Optics, dz: float) -> float:
    """Snap |dz| to the cache lattice: linear steps of DoF/8 out to where 3% of |dz|
    is bigger, geometric steps of 3% beyond. Keeps 40x on a 150 µm chamber to ~150 kernels."""
    step = optics.z_step_um()
    dz = abs(dz)
    knee = step / Z_REL_STEP
    if dz <= knee:
        return round(dz / step) * step
    return knee * (1 + Z_REL_STEP) ** round(math.log(dz / knee) / math.log1p(Z_REL_STEP))


def psf(optics: Optics, dz: float, um_per_px: float) -> np.ndarray:
    """Intensity PSF in sensor pixels for a point ``dz`` µm from focus, float32,
    odd square side, summing to <= 1 (less only when the cap truncates it).
    ``|dz|`` is snapped to a cache lattice (see ``_quantise``) and the kernel cached;
    the aberration-free PSF is symmetric in ±dz."""
    if um_per_px <= 0:
        raise ValueError(f"um_per_px must be > 0, got {um_per_px}")
    return _psf(optics, round(_quantise(optics, dz), 6), float(um_per_px))


def _grid(m: int, lam: float, na: float, d: float) -> int:
    # field 1.5x the kernel so the cyclic FFT does not fold the rings back in,
    # and at least 16 samples across the pupil
    g = max(math.ceil(1.5 * m), math.ceil(16 * lam / (na * d)))
    return g + g % 2


@lru_cache(maxsize=512)
def _psf(optics: Optics, dz: float, um_per_px: float) -> np.ndarray:
    lam, na, n = optics.wavelength_um, optics.na, optics.n
    reach = optics.blur_radius_um(dz) + 4 * lam / na  # disc plus a few rings
    half = min(MAX_HALF_PX, math.ceil(reach / um_per_px) + 1)
    side = 2 * half + 1
    # fine grid: odd oversampling to the band limit λ/4NA, so pixel centres land on
    # fine-grid samples; coarsened when the FFT would pass MAX_GRID
    s = max(1, math.ceil(um_per_px / (lam / (4 * na))))
    s += 1 - s % 2
    while s > 1 and _grid(side * s, lam, na, um_per_px / s) > MAX_GRID:
        s -= 2
    d = um_per_px / s
    m = side * s
    grid = _grid(m, lam, na, d)
    f = np.fft.fftfreq(grid, d)
    fx, fy = np.meshgrid(f, f, indexing="xy")
    f2 = fx**2 + fy**2
    pupil = f2 <= (na / lam) ** 2
    kz = np.sqrt(np.maximum((n / lam) ** 2 - f2, 0.0))
    field = np.where(pupil, np.exp(2j * np.pi * dz * (kz - n / lam)), 0.0)
    amp = np.fft.fftshift(np.fft.ifft2(field))
    inten = amp.real**2 + amp.imag**2
    total = inten.sum()
    c = grid // 2
    lo = c - m // 2
    crop = inten[lo : lo + m, lo : lo + m]
    k = crop.reshape(side, s, side, s).sum(axis=(1, 3)) / total
    k.setflags(write=False)
    return k.astype(np.float32)


def mtf(kernel: np.ndarray) -> np.ndarray:
    """Radially averaged |OTF| of a kernel, DC = 1, from DC out to Nyquist."""
    side = kernel.shape[0]
    grid = max(64, 2 * side)
    otf = np.abs(np.fft.fft2(kernel, s=(grid, grid)))
    otf /= otf[0, 0]
    f = np.fft.fftfreq(grid)
    r = np.hypot(*np.meshgrid(f, f, indexing="xy"))
    bins = np.round(r * grid).astype(int)
    n = grid // 2
    sums = np.bincount(bins.ravel(), otf.ravel(), minlength=n + 1)[: n + 1]
    counts = np.bincount(bins.ravel(), minlength=n + 1)[: n + 1]
    return sums / np.maximum(counts, 1)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--na", type=float, default=0.10)
    p.add_argument("--immersion", choices=sorted(MEDIA), default="air")
    p.add_argument("--wavelength", type=float, default=WAVELENGTH_UM, help="µm")
    p.add_argument("--um-per-px", type=float, default=1.5)
    p.add_argument("--dz", type=float, nargs="+", default=[0.0, 10.0, 30.0, 75.0], help="µm")
    a = p.parse_args(argv)
    try:
        o = Optics(a.na, a.wavelength, MEDIA[a.immersion])
        print(
            f"NA {o.na} {a.immersion}: DoF {o.dof_um:.2f} µm, Airy radius {o.airy_um:.2f} µm, "
            f"{a.um_per_px} µm/px"
        )
        for dz in a.dz:
            k = psf(o, dz, a.um_per_px)
            m = mtf(k)
            print(
                f"  dz {dz:7.2f} µm: kernel {k.shape[0]:4d} px, peak {k.max():.3f}, "
                f"energy {k.sum():.3f}, MTF min in band {m[1 : len(m) // 2].min():.4f}"
            )
    except ValueError as e:
        print(f"optics: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
