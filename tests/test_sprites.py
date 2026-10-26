"""The sprite renderer's contract: every species renders at every size, the
darkfield look is a bright rim around a dimmer interior (and the inverse under
brightfield), textures are seed-stable, rotation rotates, contraction shrinks,
and compositing only ever brightens a darkfield or darkens a brightfield."""

from __future__ import annotations

import numpy as np
import pytest

from species import SPECIES
from sprites import (
    POLARITIES,
    SpriteState,
    canvas_px,
    composite,
    demo_state,
    render_sprite,
    sprite_sheet,
    stentor_length,
)

NAMES = sorted(SPECIES)


def _state(name: str, length: float, **kw) -> SpriteState:
    sp = SPECIES[name]
    return SpriteState(length_px=length, width_px=length * sp.aspect, **kw)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("length", [6.0, 30.0, 120.0])
def test_every_species_renders_at_every_size(name, length):
    sig, side = render_sprite(SPECIES[name], _state(name, length, heading=0.7, seed=3))
    assert sig.shape == (side, side, 2) and sig.dtype == np.float32
    assert side % 2 == 1 and side >= 9
    assert sig.min() >= 0 and sig.max() <= 1
    assert sig[..., 0].max() > 0.3 and sig[..., 1].max() > 0.3


@pytest.mark.parametrize("name", NAMES)
def test_demo_cycle_is_valid_for_every_phase(name):
    sp = SPECIES[name]
    for k in range(12):
        st = demo_state(sp, k / 12, 80.0, seed=1)
        assert 0 <= st.contraction <= 1
        assert 0 <= st.neck <= sp.motion.neck_reach / (sp.length_um / 80.0) + 1e-6
        sig, _ = render_sprite(sp, st)
        assert sig.max() > 0


def test_darkfield_rim_is_brighter_than_interior_and_brightfield_rim_is_darker():
    sig, side = render_sprite(SPECIES["paramecium"], _state("paramecium", 100.0, seed=5))
    c = side // 2
    df, bf = sig[..., 0], sig[..., 1]
    # along the long axis: the rim sits at +-50 px, the interior at the centre
    rim_df = max(df[c, c + 49], df[c, c + 50], df[c, c + 48])
    interior_df = float(np.median(df[c - 5 : c + 6, c - 20 : c + 21]))
    assert rim_df > interior_df + 0.3, (rim_df, interior_df)
    rim_bf = max(bf[c, c + 49], bf[c, c + 50], bf[c, c + 48])
    interior_bf = float(np.median(bf[c - 5 : c + 6, c - 20 : c + 21]))
    assert rim_bf > interior_bf + 0.2, (rim_bf, interior_bf)
    assert interior_df > 0.05  # translucent, not hollow
    assert df[2, 2] == 0 and bf[2, 2] == 0  # background stays background


def test_texture_is_seed_stable_and_seed_dependent():
    a, _ = render_sprite(SPECIES["paramecium"], _state("paramecium", 60.0, seed=1))
    b, _ = render_sprite(SPECIES["paramecium"], _state("paramecium", 60.0, seed=1))
    c, _ = render_sprite(SPECIES["paramecium"], _state("paramecium", 60.0, seed=2))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_flicker_rng_only_touches_the_halo():
    sp = SPECIES["paramecium"]
    a, _ = render_sprite(sp, _state("paramecium", 60.0, seed=1), np.random.default_rng(1))
    b, _ = render_sprite(sp, _state("paramecium", 60.0, seed=1), np.random.default_rng(2))
    diff = np.abs(a[..., 0] - b[..., 0])
    assert diff.max() > 0  # the halo flickers
    assert diff.max() < 0.3  # but the body does not change


def test_heading_rotates_the_sprite():
    sp = SPECIES["paramecium"]
    flat, _ = render_sprite(sp, _state("paramecium", 80.0, heading=0.0))
    up, _ = render_sprite(sp, _state("paramecium", 80.0, heading=np.pi / 2))
    xs, ys = np.nonzero(flat[..., 0] > 0.1)
    assert np.ptp(ys) > 1.8 * np.ptp(xs)  # long along x
    xs, ys = np.nonzero(up[..., 0] > 0.1)
    assert np.ptp(xs) > 1.8 * np.ptp(ys)  # long along y


def test_stentor_contraction_collapses_the_silhouette():
    sp = SPECIES["stentor"]
    open_, side = render_sprite(sp, _state("stentor", 160.0, contraction=0.0), canvas=201)
    shut, _ = render_sprite(sp, _state("stentor", 160.0, contraction=1.0), canvas=201)
    a0 = (open_[..., 0] > 0.08).sum()
    a1 = (shut[..., 0] > 0.08).sum()
    assert a1 < 0.45 * a0, (a0, a1)
    assert stentor_length(160.0, 1.0) < 0.3 * 160.0
    assert stentor_length(160.0, 0.0) == 160.0


def test_lacrymaria_neck_extends_the_footprint():
    sp = SPECIES["lacrymaria"]
    short, _ = render_sprite(sp, _state("lacrymaria", 40.0, neck=0.0), canvas=301)
    long, _ = render_sprite(sp, _state("lacrymaria", 40.0, neck=120.0), canvas=301)
    xs0 = np.nonzero(short[..., 0] > 0.1)[1]
    xs1 = np.nonzero(long[..., 0] > 0.1)[1]
    assert np.ptp(xs1) > np.ptp(xs0) + 90


def test_shrink_scales_everything_down():
    sp = SPECIES["paramecium"]
    full, _ = render_sprite(sp, _state("paramecium", 80.0), canvas=121)
    small, _ = render_sprite(sp, _state("paramecium", 80.0, shrink=0.25), canvas=121)
    assert (small[..., 0] > 0.1).sum() < 0.15 * (full[..., 0] > 0.1).sum()


def test_canvas_fits_the_sprite():
    for name in NAMES:
        sp = SPECIES[name]
        side = canvas_px(sp, 50.0, 50.0 * sp.aspect, neck_reach_px=70.0)
        st = _state(name, 50.0, neck=70.0 if sp.look.neck else 0.0, heading=0.3)
        sig, got = render_sprite(sp, st)
        assert got == side
        # nothing touches the border (bilinear rotation may leave float dust)
        assert sig[0].max() < 1e-3 and sig[-1].max() < 1e-3
        assert sig[:, 0].max() < 1e-3 and sig[:, -1].max() < 1e-3


def test_composite_only_brightens_darkfield_and_only_darkens_brightfield():
    sig, side = render_sprite(SPECIES["paramecium"], _state("paramecium", 40.0))
    dark = np.full((100, 120), 18.0, np.float32)
    composite(dark, sig, 60, 50, "darkfield")
    assert dark.min() == 18.0 and dark.max() > 150
    bright = np.full((100, 120), 225.0, np.float32)
    composite(bright, sig, 60, 50, "brightfield")
    assert bright.max() == 225.0 and bright.min() < 100


def test_composite_clips_at_frame_edges_and_off_frame():
    sig, side = render_sprite(SPECIES["paramecium"], _state("paramecium", 40.0))
    frame = np.full((60, 80), 18.0, np.float32)
    composite(frame, sig, -5, 3, "darkfield")  # partly outside
    composite(frame, sig, 500, 500, "darkfield")  # fully outside
    composite(frame, sig, 79, 59, "darkfield")
    assert frame.shape == (60, 80) and frame.max() > 18.0


def test_composite_rejects_unknown_polarity():
    sig, _ = render_sprite(SPECIES["paramecium"], _state("paramecium", 20.0))
    with pytest.raises(ValueError, match="polarity"):
        composite(np.zeros((40, 40), np.float32), sig, 20, 20, "phase")
    assert set(POLARITIES) == {"darkfield", "brightfield"}


def test_tiny_sprite_is_blank_not_an_error():
    sig, side = render_sprite(SPECIES["paramecium"], _state("paramecium", 0.5))
    assert sig.shape == (side, side, 2) and sig.max() == 0


@pytest.mark.parametrize("polarity", POLARITIES)
def test_sprite_sheet_layout_matches_atlas(polarity):
    chosen = {n: SPECIES[n] for n in ("paramecium", "stentor", "lacrymaria")}
    sheet, atlas = sprite_sheet(chosen, frames=4, cell=64, polarity=polarity)
    assert sheet.shape == (64 * 3, 64 * 4) and sheet.dtype == np.uint8
    assert atlas["cell"] == 64 and atlas["frames"] == 4
    bg = 18 if polarity == "darkfield" else 225
    for name, meta in atlas["species"].items():
        assert meta["um_per_px"] > 0 and meta["length_um"] == SPECIES[name].length_um
        for col in range(4):
            cell = sheet[meta["row"] * 64 : (meta["row"] + 1) * 64, col * 64 : (col + 1) * 64]
            assert (
                abs(int(cell.astype(int).min() if polarity == "brightfield" else cell.max()) - bg)
                > 60
            )
