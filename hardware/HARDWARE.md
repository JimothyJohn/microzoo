# Microzoo rig — hardware spec

The complete filming rig for the microcosmos tracker, from the jar on the
windowsill to the Pi that clips the footage, priced under $1,000 with the
parts already owned counted at $0. Optimised for contrast, frame rate and
determinism, in that order. Magnification is explicitly not a goal
(`CLAUDE.md`, "Contrast beats magnification").

Companion files: `bom.csv` (cart-ready part list, one row per purchasable
item, with vendor, SKU, price, stock and how each figure was checked),
`SOURCING.md` (where to buy, how to read a used-scope listing, the per-gate
plan with time, cash and calendar), `index.html` (the visual front page),
`../cad/` (printed parts, empty until G2). Written 2026-10-25 against
`master` 6cf21af. Nothing beyond the TOMLOV has been bought; every row in
the BOM names the gate that unlocks it.

## 1. The rig in one paragraph

A **used compound microscope** (Olympus CH-2/CH30 or Nikon Alphaphot
class, binocular is fine, 4x and 10x achromats, 1.25 NA Abbe condenser) with its halogen
replaced by a **3 W LED on a constant-current driver** and a **printed
darkfield patch stop** in the condenser filter tray. In one eyepiece
tube, a **0.5x reducing C-mount adapter** feeds a **global-shutter camera**
(Arducam AR0234 over USB 3 into the Mac Studio first; the Raspberry Pi
Global Shutter Camera on a **Raspberry Pi 5 8 GB** is the other path, §2).
The capture box records 60 fps at ≤2 ms exposure into a ring buffer, runs
`track.py` live, and writes clips to an SSD.
A **NEMA 11 stepper on a TMC2209** turns the fine-focus knob through a
printed coupler for autofocus; it is the only motor. The sample sits in a
**120 µm spacer chamber** on a plain slide, sealed with petroleum jelly.
The **TOMLOV TM3K-3D** already owned covers the big animals (Daphnia,
copepods, Hydra) and is the G1 instrument before any of this is bought.

## 2. Bill of materials by gate

Prices are the `bom.csv` figures on 2026-10-25, rounded. "Have" is $0.

Two purchase paths share everything except the camera and the computer.
**Path A, Pi first:** Raspberry Pi 5 + Pi Global Shutter Camera, the
roadmap as written. **Path B, Studio first:** the C-mount USB 3 Arducam
AR0234 straight into the Mac Studio for G2–G4, the Pi bought at G5 when
unattended 48 h runs need it. The fork exists because on 2026-10-25 the
Pi 5 8 GB costs $175 (memory prices; launch MSRP was $80) and the Pi GS
camera is out of stock at every US reseller checked.

**Decided 2026-10-26:** the order is Path B's (Studio captures through
G4, Pi at G5), but the scope and the camera are sourced used via Nick's
deal scanner, and resale value rather than the $1,000 line governs what
they may cost (`SOURCING.md` §4, watchlist included). The table below is
the new-parts floor; Path A survives only as the numbers it would have
cost.

| Gate | Group | Parts | Path A | Path B |
|---|---|---|---|---|
| G0 | Culture + field kit | jars, baster, pipettes, labels, strainer; all but the pipettes are probably in the kitchen | $8 (+$24 if bought) | same |
| G1 | TOMLOV capture | TOMLOV + Studio (**have**), slides, coverslips ×2, well slides, petroleum jelly | $29 (+$7) | same |
| G2 | Scope + light | used binocular CH-2 class complete ($260 asking midpoint), 0.5x 23.2 mm C-mount adapter ($56, or $20 generic), XP-L star + BuckPuck + heatsink ($34), printed stops ($0); 12 V 1 A (+$9) and filament (+$16) if not on the shelf | $350 (+$25) | same |
| G2 | Camera + compute | **A:** Pi 5 8 GB $175, PSU, cooler, case, 64 GB card, GS camera $64, cable, M.2 HAT+, 500 GB SSD $55 | $375 | — |
| | | **B:** Arducam AR0234 USB 3 C-mount $140, USB cable (+$8) | — | $140 (+$8) |
| G3 | Z axis | NEMA 11 (Pololu $40; StepperOnline $18 if its site answers), TMC2209 $10, coupler $5, 12 V 3 A (+$14), jumpers (+$4) | $55 (+$18) | same |
| G4 | Chamber | Kapton tape (+$8); SecureSeal and 3M 9495LE are $131 and $100 options, qty 0 | $0 (+$8) | same |
| | **Total, buy list** | | **$816** | **$582** |
| | **Total if every "maybe" is bought too** | | **$898** | **$672** |
| | With a $400 trinocular instead of the $260 binocular | | $1,038 | $812 |
| | Path B plus the Pi at G5 (Pi set without camera, $308) | | — | $980 |

Figures are `bom.csv` extended prices on 2026-10-25, before tax and
shipping. The spread is the used scope and, for Path A, the Pi. The
recommendation (`SOURCING.md` §1) is Path B with the binocular: the full
tracking rig for about $670, the Pi added at G5 for about $310 when stock
and prices have had months to move, and the whole thing still under the
line.

## 3. Why these parts

**A used finite-tube Olympus CH-2 / Nikon Alphaphot class scope, binocular
is fine.** The optics are better than anything new at the price, the
160 mm finite tube means a plain 0.5x relay works without infinity-corrected
tube-lens games, and RMS 160/45 objectives are interchangeable with new
AmScope achromats at $18–21 if one arrives damaged. Complete binocular
CH-2s with four objectives and the 1.25 NA Abbe condenser list at
$220–300. Trinocular CH-2s are rare, cost more, and their photo tube is a
25 mm plain tube sized for Olympus' own PM-ADF adapter rather than a
23.2 mm eyepiece tube, so a generic adapter may not fit it anyway. The
camera therefore goes in one eyepiece tube on a 23.2 mm 0.5x adapter and
the other eyepiece stays for aiming; the live view on a screen is the
real viewfinder. The risks (missing parts, fungus, seized focus) are
listed with checks in `SOURCING.md` §3. A new AmScope B120C ($300,
binocular, LED, 1.25 NA Abbe, 23 mm tubes) is the fallback if nothing
good shows up in two weeks; its condenser and objectives are coarser.

**0.5x reducer, not a bare 1x C-mount tube.** The sensor is 5 mm wide.
At 1x relay a 4x objective gives a 1.25 mm field: a Paramecium crosses it
in a second and the tracker has nothing to track. At 0.5x the field is
2.5 mm × 1.9 mm (Pi GS) or 2.9 × 1.8 mm (AR0234) and sampling is at the
Rayleigh limit of the objective (§4). The reducer also makes the camera
parfocal with the other eyepiece, within the adapter's focus travel.

**Darkfield by printed patch stop.** The condenser must illuminate at an
NA above the objective's NA (0.10 at 4x, 0.25 at 10x) and nothing below
it. A black disc on a clear carrier in the filter tray does exactly that
for a 1.25 NA Abbe condenser, at the cost of most of the light. Disc
diameter is a function of the condenser's focal length and the objective
NA, so it is a printed, parametrised part (`cad/`, measured on the actual
scope). Oblique illumination (a half-disc, same tray) is the fallback if
darkfield at 10x is too dim at 2 ms. A dedicated dry darkfield condenser
is a $60–100 upgrade, not needed to start.

**LED, not the halogen.** Three reasons: no heat into the sample (halogen
drives convection that reads as drift and cooks the culture), constant
colour at any brightness, and a flat spectrum that MOG2 does not care
about. 3 W of neutral white through a CC driver is plenty for brightfield
and workable for darkfield at 4x; whether it is enough for darkfield at
10x and 2 ms is bring-up step 6. The LED sits on the halogen's heatsink
or a 20 mm star heatsink in the lamp house; the driver's PWM dim pin can
later be driven from the Pi for strobe.

**Global shutter, two ways to get it.** A rolling shutter smears a 1 mm/s
swimmer across 11 rows per frame, so the sensor is global shutter either
way. **Path A:** the Raspberry Pi Global Shutter Camera (IMX296) on a
Pi 5. Supported by `libcamera`/`picamera2` out of the box, C/CS mount so
the reducer threads straight on, 1456×1088 at 60 fps documented by
Raspberry Pi. On 2026-10-25 it is out of stock at Adafruit, CanaKit and
PiShop and ambiguous at SparkFun. **Path B:** the Arducam AR0234 USB 3
camera with a C/CS mount (UCTRONICS B0495, $140) into the Mac Studio. It
is a UVC device, so OpenCV opens it with no driver; 1920×1200 at 3 µm
gives 40% more pixels and 15% finer sampling than the IMX296 (§4), which
is the difference that matters for species at 10x; and the Pi's missing
hardware encoder stops being a problem because the Studio does the
capture. Its measured frame rate at full resolution over USB 3 is
bring-up step 4. The Pi-CSI AR0234 (B0353) is M12 fixed-lens only and
is not an option for a microscope. Path B moves the Pi purchase to G5;
the architecture (`CLAUDE.md`, "Keep the Pi dumb") does not change, the
same UVC camera plugs into the Pi 5's USB 3 port when it arrives.
**Third way, since 2026-10-26:** a used USB3 Vision global-shutter camera
(Basler ace, FLIR Blackfly S, Daheng; `SOURCING.md` §4) if the scanner
finds one, because it resells. Same C-mount, same reducer, same numbers
for the 1920×1200 models; the cost is a vendor SDK instead of UVC, on
the Studio now and on the Pi at G5.

**Pi 5 8 GB (Path A now, Path B at G5).** `track.py` on a 1080p frame at `--scale 0.5` runs in a
few ms on the Studio; the Pi 5 has roughly a tenth of that CPU, which is
why detection runs on the downscaled frame and crops from full-res. 8 GB
is for the ring buffer: 10 s of pre-roll at 60 fps is 600 frames, 1 GB at
8-bit mono for the IMX296. **The Pi 5 has no hardware video encoder**, so
the hour-long raw capture goes to the SSD as MJPEG (~35 GB/h, §6) and the
Studio transcodes offline; software H.264 at 60 fps is a bring-up test,
not a plan.

**NEMA 11 + TMC2209 for Z only.** Fine-focus knobs move 100–200 µm per
turn; at 1/16 microstepping that is 30–60 nm per microstep and the 2 µm/s
rate limit is 30–60 microsteps per second. Torque is irrelevant, silence
and resolution are the spec, and the TMC2209 over UART gives both plus
stall detection for the end stops. No XY motor: the organism rides the
water (`CLAUDE.md`).

**120 µm chamber.** Paramecium is 40–70 µm thick, so 120 µm confines it to
about two body depths: it stays within the 10x depth of field most of the
time and cannot swim out of focus vertically, without touching the glass.
Daphnia and Stentor need the 1–3 mm well slide. Spacer tape is the
cheap start; Grace Bio-Labs SecureSeal spacers are the known-thickness
upgrade. Petroleum jelly around the coverslip edge stops evaporation and
the flow it causes.

## 4. Optical numbers

Finite-tube scope, eyepiece-tube camera port, 0.5x relay. Effective magnification at
the sensor is half the objective's. Rayleigh resolution 0.61 λ/NA at
550 nm. "Nyquist" is whether the pixel at the sample is at or below half
the Rayleigh distance. Depth of field is λ/NA² + pixel/(M·NA). Motion
numbers are for a Paramecium at 1 mm/s.

| Sensor | Obj | µm/px | Field (mm) | Rayleigh (µm) | Nyquist | DoF (µm) | px/frame @60 fps | Blur @2 ms | Blur @1 ms |
|---|---|---|---|---|---|---|---|---|---|
| IMX296 1456×1088, 3.45 µm | 4x NA 0.10 | 1.73 | 2.51 × 1.88 | 3.4 | at the line | 72 | 9.7 | 1.2 px | 0.6 px |
| | 10x NA 0.25 | 0.69 | 1.00 × 0.75 | 1.3 | at the line | 12 | 24 | 2.9 px | 1.4 px |
| | 40x NA 0.65 | 0.17 | 0.25 × 0.19 | 0.5 | yes | 1.6 | 97 | 12 px | 6 px |
| AR0234 1920×1200, 3.0 µm | 4x NA 0.10 | 1.50 | 2.88 × 1.80 | 3.4 | yes | 70 | 11 | 1.3 px | 0.7 px |
| | 10x NA 0.25 | 0.60 | 1.15 × 0.72 | 1.3 | yes | 11 | 28 | 3.3 px | 1.7 px |
| | 40x NA 0.65 | 0.15 | 0.29 × 0.18 | 0.5 | yes | 1.5 | 111 | 13 px | 7 px |

Reading it:

- At 4x both sensors sample at the objective's resolution limit, so
  neither wastes pixels and neither is the bottleneck: the 4x achromat is.
  The tracking view is a 2.5–2.9 mm field at 1.5–1.7 µm/px.
- At 10x the IMX296 is 3% coarser than Nyquist and the AR0234 is 10% finer.
  For blob tracking this is nothing. For telling Didinium's two cilia belts
  from a Coleps at 10x it is the difference the AR0234 buys.
- Exposure: 2 ms holds blur near 1 px at 4x; the follow view at 10x wants
  1 ms. Darkfield light budget (§5) is sized to 1 ms at 10x.
- 40x is a stationary-subject view only: 1.5 µm depth of field and 100 px
  of travel per frame.
- Depth of field at 10x (11 µm) against a 120 µm chamber is why Z is
  motorised and why a chamber deeper than 200 µm is pointless for ciliates.

The formulae are in this section so the table can be redone in a line.

## 5. Light budget, measured not modelled

The darkfield fraction that reaches the sensor depends on the stop size,
the condenser, the organism and the slide, so the budget is a
measurement with a pass mark:

1. Brightfield, 4x, LED at full current, 2 ms, analog gain 1: the
   background must clip or nearly clip (≥ 240/255). If it does not, the LED
   or the driver is undersized; the fix is current (up to the LED's rating)
   before it is a bigger LED.
2. Darkfield stop in, 4x, 2 ms, gain ≤ 4: a Paramecium body reads ≥ 80/255
   above a background ≤ 20/255. Pass → tracking view is done.
3. Darkfield, 10x, 1 ms, gain ≤ 8: same thresholds. Pass → follow view is
   done. Fail → try the oblique half-stop at gain ≤ 4, then a smaller stop
   (lower cut-in NA, some glare), then the dry darkfield condenser.

Gain ceilings are there because MOG2 thresholds on absolute difference;
noise above ~8x gain starts spawning false blobs at `--min-area 30`.

## 6. Capture and storage

| Mode | Rate | Per hour | Where |
|---|---|---|---|
| Raw 8-bit mono, IMX296, 60 fps | 95 MB/s | 342 GB | ring buffer only, never disk |
| Raw 8-bit mono, AR0234, 60 fps | 138 MB/s | 498 GB | ring buffer only |
| MJPEG q≈90 (~10:1) | ~10 MB/s | ~35–50 GB | USB 3 SSD on the Pi; the hour-long G3 run |
| H.264 CRF 23 (Studio transcode) | ~1 MB/s | ~3.6 GB | archive |
| Event clips, 10 s pre-roll + event | | tens of MB each | the deliverable |

A 500 GB SSD holds ten G3 hours before the Studio pulls and transcodes.
The Pi 5's USB 3 ports sustain MJPEG easily; bring-up step 4 confirms the
achieved CSI-2 frame rate with `picamera2`, which is the only number that
counts.

## 7. Pin budget on the Pi 5

| Function | Pins | Notes |
|---|---|---|
| Camera | CAM/DISP 0 (22-pin) | one camera; the second connector stays free for a top-light camera later |
| TMC2209 UART | GPIO14 TX, GPIO15 RX (UART0) | single-wire half-duplex: TX through 1 kΩ to the driver's PDN_UART, RX direct |
| TMC2209 STEP / DIR / EN | GPIO 18, 23, 24 | STEP on a PWM-capable pin for rate-limited moves |
| LED driver dim / strobe | GPIO 12 (PWM0) | optional, G4+ |
| End-stop (stall via DIAG) | GPIO 25 | TMC2209 DIAG pulse on stall, no mechanical switch |
| Storage | USB 3 | SSD |
| Network | Ethernet | to the Studio for offline classification |

The stepper's 12 V comes from its own supply; only logic and ground are
shared with the Pi. Nothing here needs a HAT; a 40-pin breakout and six
jumpers are enough for v2, and a small protoboard once it works.

## 8. Bring-up checklist

Each step has a pass condition. Stop at the first fail and fix it; the
later steps assume the earlier ones.

| # | Step | Pass |
|---|---|---|
| 1 | Scope arrives: clean, check coarse/fine focus travel, stage, condenser rack, diaphragm, all objectives present and clear | Eyepiece image of a stage micrometer or a ruler sharp at 4x and 10x |
| 2 | Halogen out, LED + driver in, powered from the bench supply | Even brightfield at 4x with the field diaphragm just outside the view |
| 3 | Reducer in the right eyepiece tube, camera on the reducer, a still frame | Camera image parfocal with the left eyepiece within the adapter's travel |
| 4 | 60 fps capture at full resolution, 2 ms exposure, mono (`picamera2` on the Pi, OpenCV/V4L2 or AVFoundation on the Studio) | Measured ≥ 59 fps for 60 s, no dropped frames in the metadata |
| 5 | Print the darkfield stop from the measured condenser tray diameter (`cad/`) | Light budget §5 step 2 passes |
| 6 | Light budget §5 step 3 at 10x | Pass, or a documented fall back to oblique |
| 7 | `track.py` live on the Pi at `--scale 0.5`, synthetic test first, then the jar | ≥ 30 fps processing on 1080p, stable IDs on the Paramecium bloom |
| 8 | MJPEG to SSD for 60 min alongside live tracking | Zero dropped frames, SSD write ≤ 50 MB/s, Pi CPU temp < 75 °C |
| 9 | Stepper on the fine-focus knob through the printed coupler, 1/16 microstep, UART up | Sharpness-vs-position curve at 10x; stall detection fires at both ends of travel |
| 10 | Autofocus loop (`v2`) on a swimming Paramecium | Held in focus 60 s; the G4 plot |

Steps 1–8 are G2 and G3; steps 9–10 are G3 and G4.

## 9. Open decisions

Decided for now, revisit only on the evidence named.

| Decision | Current | Revisit when |
|---|---|---|
| Camera | used USB3 Vision global shutter (Basler/FLIR class) if the scanner finds one; AR0234 USB 3 C-mount as the floor; decided 2026-10-26 | the scanner has nothing by the time G2 passes → buy the AR0234 new |
| Scope | used, resale-strong first (Olympus BX / Nikon Eclipse class, trinocular if the relay comes with it), CH-2 class binocular as the floor; decided 2026-10-26 | no complete listing of either class by G2 → new AmScope B120C |
| Capture box for G2–G4 | Mac Studio + the USB 3 camera; Pi at G5 (decided 2026-10-26) | G5 |
| Darkfield | printed Abbe patch stop | §5 step 3 fails on stop and oblique → dry darkfield condenser |
| Capture format | MJPEG to SSD | bring-up step 8 shows the Pi can software-encode H.264 at 60 fps with headroom → switch |
| Chamber | 120 µm tape spacer | tape thickness varies > 20% between batches → SecureSeal |
| Microstepping | 1/16 | focus hunting visible in footage → 1/64 and a slower rate |
| Pi storage | USB 3 SSD | an M.2 HAT only if the USB bus is contended by a second camera |

Not decisions, facts: the TOMLOV stays the Daphnia instrument; the Studio
does all ML; no XY motor.

## 10. Not in the kit, on purpose

- Any new compound microscope above $500, any phase-contrast kit, any
  objective above 40x. The 4x and 10x do the work.
- A new Tier 2 machine-vision camera (Daheng/Basler/FLIR, $300–600).
  Used, it is on the G2 watchlist under the 2026-10-26 resale rule; new,
  only if the G5 footage shows cropping is the limit.
- Motorised XY stage. Core decision, see `CLAUDE.md`.
- Pi camera lenses: the microscope is the lens.
- A second Pi or a Jetson. The Pi 5 is the ceiling for the dumb half.
- Methylcellulose, stains, fixatives. Ecology footage only.
