# LED ring: darkfield, oblique and colour for the TOMLOV, driven by the Pi

**What it is.** A printed riser that lifts a 60 × 15 mm Petri dish so the water sits just
under the TOMLOV lens when the arm bottoms out (lens at 17.91 mm above the stage). Under the
dish, a ring of 21 WS2812B LEDs (IP67 tape, 100/m) lights the sample at 75° from vertical. With the TOMLOV backlight
off and the black stop in the cutout, that is darkfield. Light an arc instead of the whole
ring and it's oblique illumination; switch the stop for the diffuser and the TOMLOV
backlight gives brightfield. A tab takes a plate to the Meca500 flange. Source:
[`cad/dish_ring.scad`](../cad/dish_ring.scad).

**Before printing, measure and tell me:**

| Parameter | Default | How |
|---|---|---|
| LED type | WS2812B IP67 **tape** | 12 mm bullet pixels *don't fit*: see Geometry |
| `STRIP_W`, `STRIP_T`, `STRIP_PITCH` | 12, 4.5, 10 mm (100/m) | calipers across and through the silicone sleeve; count LEDs over 10 cm |
| `DISH_OD`, `DISH_FLOOR_T`, `DISH_FOOT`, `DISH_H` | 60, 1.0, 0, 15 | calipers on the **base**, not the lid: "60 × 15" is often the lid, the base a few mm smaller. `DISH_FOOT` is the recess under the floor, if any |
| `LENS_D` | 35 mm | lens nose diameter: it must dip inside the dish (inner ⌀ 58) |
| `BACKLIGHT_D` | 30 mm | lit window in the TOMLOV base |
| `MECA_BCD`, `MECA_HOLES`, `MECA_PIN_*` | unset | Meca500 flange drawing or calipers; the adapter refuses to render without it |

**Three rules that matter more than the CAD:**
1. **Colour values 0 or 255 only.** WS2812B dims by PWM at about 400 Hz. Against a 2 ms
   exposure (and the TOMLOV's rolling shutter) that shows up as brightness flicker and
   banding. Full-on channels are DC: no flicker. Set brightness by how many LEDs are lit.
2. **One colour channel, and not every LED.** 21 LEDs all green is about 2 W, a few mm from
   the dish edge; all white is about 6 W. Heat means convection, which reads as drift
   (CLAUDE.md). Start with every third LED in one colour (≈0.7 W), add more only if the
   image needs it, and check the water temperature after an hour.
3. **Every clip's sidecar records the light state:** mode, colour, which LEDs, plus the
   TOMLOV backlight on/off. Future labels depend on it.

---

## Geometry

z = 0 is the TOMLOV stage. Defaults, checked against every assert in the `.scad`:

| | z (mm) |
|---|---|
| lens bottom (arm bottomed out) | 17.91 |
| water surface (`WATER_GAP` 1.0 below the lens) | 16.91 |
| sample, mid-water (the LEDs aim here) | 15.91 |
| dish floor top (`WATER_DEPTH` 2.0) | 14.91 |
| dish stands on the seat ring | 13.91 |
| base wall top / seat ring underside | 11.91 |
| LED centres, r = 36 | 6.5 |
| strip groove floor | 1.0 |

- **Base:** OD 93 mm, 11.9 mm tall; the seat ring is 97 mm OD.
- **LEDs:** 21 at 100/m. One pitch is left for the cut, with the leads out of a slot
  opposite the tab.
- **Strip tilt is not the aim.** A 12 mm sleeve aimed straight at the sample (15° up) needs
  11.6 mm of height and there is 10.9. So the land tilts the strip 30° up, and the sample
  sits 15° off the LED axis, well inside the ~120° beam. `LAND_TILT` and `LED_Z` are the
  knobs; the asserts say when the strip stops fitting.
- **Chief ray:** 75° from vertical in air. It enters the dish floor 7.7 mm off axis and
  runs at 47° in the water, just under the 48.8° total-internal-reflection angle. Direct
  light leaves the surface at a grazing angle, far outside anything the lens accepts. Put
  the LEDs lower and the direct light TIRs back down instead: darker still.
- **The lens dips into the dish.** The rim is at about 28.9 mm. That's why `LENS_D` must be
  below the dish's inner diameter; otherwise use a lid or a shallow dish
  (`DISH_H` < 3.5 mm).
- **Bullet pixels are out.** A 12 mm pixel string needs about 11.5 mm of height, aimed this
  shallow. There's about 10.9 mm under the seat ring, because the dish floor has to be at
  14.9 mm. If your strand is bullet pixels, the ring needs a different layout (pixels
  outside the dish, aimed down through a side window). Say so and I'll draw it.

**Parts** (print matte black PLA, except the diffuser):

| `part=` | Notes |
|---|---|
| `base` | backlight cutout with an insert counterbore, conical strip land, cable slot, M3 heat-set tab |
| `seat` | flat ring: the dish stands on its inner 2.5 mm, the rest roofs the LEDs. Its rim drops over the base wall to centre it. Prints flat |
| `stop` | black insert, darkfield |
| `diffuser` | 0.6 mm window in white/natural PLA: diffused TOMLOV backlight, brightfield |
| `meca_adapter` | plate from the tab to the flange |

Render with `./scripts/cad-render.sh`: STLs plus a cut-away `data/cad/dish_ring_section.png`
showing the dish, water, lens and chief ray ghosted in place. It finds OpenSCAD on PATH, in
/Applications (versioned names too), or on a mounted DMG.

## Illumination modes (all from the same ring)

| Mode | TOMLOV backlight | Insert | Ring |
|---|---|---|---|
| darkfield | off | stop | all on, one colour |
| oblique | off | stop | one 90–120° arc. CLAUDE.md's fallback when darkfield is too dim; gives relief |
| two-colour oblique | off | stop | halves in two colours: the pseudo-relief look, edges tinted by direction |
| brightfield | on | diffuser (or open) | off |
| Rheinberg-style | on, through a coloured gel on the diffuser | diffuser | ring in the contrasting colour. True Rheinberg wants a coloured centre; the backlight + gel stands in |
| mixed | low | diffuser | ring on: a bright rim over a grey ground |

The ring is addressable, so the mode can change between frames. That matters once a camera
has a trigger input (G2). The TOMLOV can't be synchronised, so there it's one mode per clip.

## Wiring (Pi 5)

```
5 V supply ──┬──────────────── strip +5 V   (inject at the strip, not through the Pi)
             ├─ 1000 µF ─┐
GND ─────────┴───────────┴──── strip GND ── Pi GND   (common ground)
Pi GPIO ── 74AHCT125 (Vcc 5 V) ── 330 Ω ── strip DIN
```

- **Level shifter.** WS2812B wants about 0.7 × 5 V for a logic high. 3.3 V works on some
  strips and not others, so use a 74AHCT125 (or any AHCT buffer at 5 V). Short data lead.
- **Power.** Budget about 20 mA per lit colour channel per LED: 21 LEDs green ≈ 0.4 A,
  all white ≈ 1.3 A. Use a separate 5 V 2 A supply; the Pi 5's own supply is spoken for.
- **Library: not `rpi_ws281x`.** The Pi 5 moved GPIO to the RP1 chip and that library no
  longer drives it. Two paths:
  - **SPI (my pick).** WS2812 bits encoded 3 SPI bits each at 2.4 MHz (`1` → `110`,
    `0` → `100`), sent on MOSI (GPIO 10, header pin 19) through `/dev/spidev0.0` with
    `spi=on`. Bit times come out at 417 / 833 ns, inside the WS2812B windows. About 40
    lines of our own code over `spidev`, with no Adafruit stack and no firmware
    dependency. A reset gap of ≥300 µs (90 zero bytes) latches the frame. Bench-check
    the timing on the scope before trusting it.
  - **Adafruit's PIO driver** (`Adafruit-Blinka-Raspberry-Pi5-Neopixel`). It works and
    leaves SPI free, but at last check it was a 1.0 release candidate. It needs firmware
    with PIO support (`/dev/pio0`) and a udev rule for non-root access. Revisit if SPI
    is needed for something else.
- **Software shape.** A small `lights.py` (not written yet): `set_mode(name, colour, arc)`,
  values clamped to 0/255, and `state()` returning a dict the capture loop writes into
  the sidecar. It also takes a CLI for the bench, e.g. `python lights.py darkfield green`.
  Deterministic and dumb, per "keep the Pi dumb".

**Gate note.** The Pi arrives with the G2 kit. Printing this ring and using it under the
TOMLOV is G1-useful and buys nothing: until the Pi is here, any Arduino/ESP32 from the
parts bin with FastLED can drive the same strip at 0/255 values.

## Meca500 mount

The base has a tab with two M3 heat-set inserts, 20 mm apart. `meca_adapter` is a 5 mm
plate: M3 screws come up through it into the tab, it runs outboard, and the flange screws
down onto its far end beside the holder.

- **Flange facts I could verify** (Mecademic knowledge base, via search; their page 404'd
  on direct fetch): M3 fasteners, **≤4 mm** thread penetration into the flange, 1.5 N·m,
  and a 2.95 mm pin for the 3 mm locating holes. So screws are plate thickness + ≤4 mm:
  M3×8 into a 5 mm plate. **The bolt-circle diameter and hole count are not verified.**
  `MECA_BCD` stays 0 and the adapter won't render until it's measured.
- **Payload:** 0.5 kg (Meca500 R3 manual, as cited in `stage.py`). Holder, dish and 5 mL
  of water come to well under 150 g.
- **An open dish on a moving arm is the slosh case.** `stagesim.py` clears a *sealed*
  150 µm chamber (closed walls, no free surface). An open well lags about 100 ms and makes
  surface waves, with the lens 1 mm above the water. Use the arm to place and swap dishes,
  and keep motion slow with the lens retracted. Or float a 22 mm coverslip on the water
  under the lens: that kills the meniscus and the ripples under the field, and gives the
  lens something flat to not touch (subtract 0.17 mm from `WATER_GAP`). Before any arm
  motion near the lens, the soft Z limit in `stage.py` has to include the water surface,
  not just the dish.
