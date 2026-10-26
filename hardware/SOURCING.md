# Sourcing plan — vendors, the used-scope hunt, the two paths, budget and schedule

Companion to `HARDWARE.md` (what the rig is and why), `bom.csv` (cart-ready
part list) and `index.html` (the visual version). Vendor facts were checked
against vendor pages on 2026-10-25; each table says how. Prices are USD
before tax and shipping.

**Verification legend.** *verified* = the vendor's own page was loaded that
day and the figure read from it. *snapshot* = the figure came from a search
summary of the vendor page, age unknown. *estimate* = a round number with
no vendor page. eBay, Amazon, DigiKey, Mouser, Micro Center, StepperOnline,
Carolina, Bambu and arducam.com block automated readers; amscope.com
rate-limits them. Every figure from those is a snapshot; the SKUs are exact
search strings and a browser settles each in a minute.

## 1. Recommendation in three lines

1. **Tomorrow costs nothing.** The pond trip (§7) and G1 on the TOMLOV need
   only pipettes, slides and coverslips (~$25, Home Science Tools). Nothing
   else is bought until G1 produces a tracked clip and G2 shows the
   TOMLOV's floor.
2. **At G2, buy a complete used binocular Olympus CH-2 class scope
   ($220–300), the LED kit ($34) and the USB 3 AR0234 C-mount camera
   ($140) into the Mac Studio: Path B.** About $670 all-in with the Z axis
   and consumables. The Pi 5 is deferred to G5 because today it costs $175
   and its camera is out of stock everywhere; the architecture does not
   change, only the order of purchase.
3. **Path A (Pi 5 + Pi GS camera first) is $225 more today** and lands at
   about $900 with the same scope. Take it only if the Pi has to be in the
   loop from day one or if the Pi GS camera reappears at $50 and the Pi 5
   drops back under $100.

## 2. Component vendors

Full detail with URLs is in `bom.csv`. The short version, by group:

| Part | Buy from | Part no. | Price | Stock 2026-10-25 | Status |
|------|----------|----------|-------|------------------|--------|
| Used Olympus CH-2 / CHT binocular, complete | eBay | search `olympus ch-2 microscope` | $220–300 asking | several | snapshot |
| Used Nikon Alphaphot / Labophot | eBay, dotmed | | $123–550 asking | few | snapshot |
| New fallback: AmScope B120C | amscope.com | B120C | $299.99 | listed | verified |
| 0.5x C-mount adapter, 23.2 mm | AmScope | RU050 | ~$56 | listed | snapshot |
| 0.5x C-mount adapter, generic | Amazon / eBay | "0.5X 23.2mm C-mount reduction lens" | $15–25 | | snapshot |
| Cree XP-L 20 mm star, 4000 K | LEDsupply | CREEXPL-740-1 | $8.36 | warm bins intermittent | verified |
| BuckPuck 700 mA wired, dimmable | LEDsupply | 3023-D-E-700 | $19.41 | 547 | verified |
| 3 W star heatsink | LEDsupply | HS13137 | $6.25 | in stock | verified |
| 12 V 1 A supply | Adafruit | 798 | $8.95 | in stock | verified |
| Spare 4x / 10x achromat 160/45 | AmScope | A4X-YX-V460 / A10X-YX-V460 | $17.99 / $20.99 | listed | verified |
| Dry darkfield condenser (fallback) | AmScope | DK-DRY100 | ~$138 | listed | snapshot |
| **Path B** AR0234 USB 3 global shutter, C/CS mount | UCTRONICS | B0495 | $139.99 | listed | verified |
| **Path A** Raspberry Pi 5 8 GB | PiShop.us / CanaKit | 8GB-9028 / PI5-8GB | $175 | in stock | verified |
| **Path A** Pi 27 W PSU, Active Cooler, case, 64 GB card | PiShop.us | 1795-1, 374-1, 1272-1, 274-1 | $12.95, $10.95, $10.95, $30.95 | in stock | verified |
| **Path A** Pi Global Shutter Camera | SparkFun | SEN-21803 | $63.75 | in stock / backorder (ambiguous) | verified |
| **Path A** same | Adafruit / CanaKit / PiShop | 5702 / RSP-CAM-GS / 2103-1 | $50 / $53.95 / $55 | **out of stock** | verified |
| **Path A** 22-to-15-pin camera cable 300 mm | Adafruit | 5819 | $3.16 | in stock | verified |
| **Path A** M.2 HAT+ | PiShop.us | 3076 | $12 | in stock | verified |
| NEMA 11 stepper | Pololu | 1205 | $39.92 | backorder OK | verified |
| NEMA 11 stepper, cheaper | StepperOnline | 11HS12-0674S | $17.90 | site blocked the check | snapshot |
| NEMA 8 alternate | Adafruit | 4411 | $19.95 | 89 | verified |
| TMC2209 driver | BIQU (BigTreeTech) | TMC2209 V1.3 | $9.99 ($6.94 sale) | listed | snapshot |
| 5→5 mm flex coupler | Adafruit | 1175 | $4.95 | in stock | verified |
| Slides 72-pk / coverslips #1 100-pk | Home Science Tools | MS-SLIDP72 / MS-SLIDCV | $7.95 / $3.95 | in stock | verified |
| Depression slides 12-pk | Microscope World | SDS | $12.95 | unclear | verified |
| SecureSeal 120 µm spacers, 100-pk | Grace Bio-Labs | 654002 | $131 | listed | verified |
| 3M 9495LE 170 µm tape | Uline | S-16638 | $50/roll, 2-roll min | in stock | verified |
| Paramecium / Didinium living culture (fallback) | Carolina | 131554 / 131460 | $10.55 each | ships to need-by date | snapshot |
| Bambu PLA Matte 1 kg | Bambu Lab US | PLA Matte refill | $15.99 | listed | snapshot |

Notes that change what you buy:

- **Binocular, not trinocular.** Complete trinocular CH-2s are rare; the
  CH-2 trinocular phototube is a 25 mm plain tube for Olympus' own PM-ADF
  adapter (alanwood.net, verified), not a 23.2 mm eyepiece tube, so the
  generic adapter may not fit the port you paid extra for. Put the camera
  in an eyepiece tube.
- **Check the eyepiece tube bore.** The RU050 and the generic adapters are
  23.2 mm. Olympus CH-2 and Nikon Alphaphot eyepieces are 23.2 mm; the
  AmScope B120C says "23 mm". Ask the seller for the eyepiece barrel
  diameter or a photo with a ruler before buying the adapter.
- **The generic $20 adapter is probably fine.** The RU050 adds the 30 and
  30.5 mm sleeves and a known focal design. Buy generic first; if the
  camera cannot be made parfocal with the eyepiece, the RU050 is the fix.
- **LED colour temperature does not matter to the tracker.** 4000 K is
  the compromise for footage that also looks right; 3000 K is the same
  price. No 90 CRI star is stocked anywhere found; 80 CRI is what there is.
- **12 V once.** The G3 12 V 3 A supply can feed the BuckPuck too (7–32 V
  in). Buy the Adafruit 1 A only if G2 happens months before G3.
- **StepperOnline before Pololu.** Same NEMA 11 class, $18 vs $40, but
  omc-stepperonline.com refused the automated check and its Tindie store
  is closed. One browser visit decides.
- **Chamber tape.** Both proper spacer products cost over $100. Start with
  coverslip shims (a #1 coverslip is 130–170 µm; snap strips off one) and
  Kapton stacks; buy SecureSeal when footage is being published.
- **Pi prices are memory prices.** $175 for the 8 GB board is more than
  double launch MSRP; the official 64 GB card is $31. If Path A is chosen,
  PiShop separates ($241 for board, PSU, cooler, case, card) beat the
  CanaKit bundle ($270) and give official parts.
- **Pi GS camera supply is tight.** SparkFun shows both "in stock" and
  "backorder". If Path A, order it the day it is decided.
- **Carolina cultures ship to a need-by date.** Residential delivery to
  Texas is not stated on the site; call 800-334-5551 before ordering. Only
  if the pond fails by day 10.

## 3. Buying a used microscope without getting burned

What a listing must show or the seller must answer. Thirty minutes of
questions saves a $250 doorstop.

**Must have, in the photos or the answers**

- Four objectives in the turret, including a **4x and a 10x** (the 40x and
  100x are nice; the 4x is the tracking view and the hardest to find used).
  Olympus A, EA or DPlan; Nikon E or CF. Any RMS 160/45 objective fits.
- A **1.25 NA Abbe condenser** on a focusing rack with an iris. The
  darkfield stop goes in its filter tray; no tray, no stop. A swing-out
  top lens is a plus for 4x.
- Coarse and fine focus that **hold position** (the stage must not drift
  down under its own weight). Ask: "does the stage sink over an hour?"
- A working **illuminator** or at least the lamp house intact; the bulb is
  irrelevant since the LED replaces it. The field diaphragm should be
  present.
- **Two eyepieces**, 10x, and the barrel diameter (23.2 mm). Missing
  eyepieces are $20–40 used but confirm the bore.
- Mechanical stage with X/Y knobs and a slide clip. Plain stages with
  clips are fine for a still chamber but the mechanical stage makes
  centring a bloom pleasant.

**Red flags**

- "Powers on" as the only functional claim; "untested" at more than $150.
- Fungus: a web pattern inside an objective or the condenser in a
  close-up. Cleanable on outer surfaces only.
- Haze or delamination in the prisms (a milky view through the eyepieces).
- Stripped or slipping focus (the knob turns, the stage does not), or
  focus tension so stiff a motor could not turn it.
- Dented or bent stage, cracked base, missing condenser carrier.
- Phase-contrast heads and condensers at a premium: not needed here.

**Questions to ask the seller**

1. Which objectives exactly (read the engraving)?
2. Does fine focus move smoothly through its full range, and does the
   stage hold position?
3. Photo looking down the eyepiece tubes with eyepieces removed, and one
   of the condenser bottom.
4. Eyepiece barrel diameter, or a photo with a ruler.
5. Any fungus, haze or fogging in any optic?
6. Shipping: double-boxed, objectives and condenser removed and wrapped,
   or not at all.

**Target prices:** complete binocular CH-2 / CHT $220–300; Alphaphot
$250–350; anything above $350 should be a serviced or trinocular unit
with a photo adapter included. New AmScope B120C at $300 is the ceiling
for a new scope here.

## 4. The two paths

| | Path A: Pi first | Path B: Studio first |
|---|---|---|
| Camera | Pi Global Shutter Camera, IMX296, 1456×1088, 3.45 µm, C/CS | Arducam AR0234 USB 3, 1920×1200, 3.0 µm, C/CS |
| Capture box for G2–G4 | Raspberry Pi 5 8 GB | Mac Studio (owned) |
| Driver risk | none on the Pi (`libcamera`) | none on macOS (UVC, OpenCV) |
| Frame rate | 60 fps documented by Raspberry Pi | 60 fps at 1920×1200 is Arducam's figure; measure at bring-up |
| Encoding | Pi 5 has no hardware encoder: MJPEG to SSD | Studio encodes anything in real time |
| Sampling at 10x | 0.69 µm/px, 3% coarser than Nyquist | 0.60 µm/px, 10% finer |
| Cost today | $375 | $140 (+$8 cable) |
| Stock today | camera out of stock at 3 of 4 resellers | listed at UCTRONICS |
| Pi at G5 | already there | +$308 (board, PSU, cooler, case, card, HAT+, SSD); the USB camera moves to the Pi's USB 3 |
| Total rig with a $260 scope | ~$900 | ~$670 now, ~$980 after G5 |
| Matches the roadmap as written | yes | re-sequences v1 "Pi capture" after v2–v3; nothing else moves |

**Position:** Path B. The Studio is already on the bench and faster than
the Pi at every step the next three gates need; the Pi's job is unattended
48 h runs, which is G5; and the only part that is hard to buy today (the
Pi GS camera) is the one Path B skips. The one thing Path B must prove
early is the AR0234's real frame rate over USB 3 at full resolution
(bring-up step 4); if it cannot hold 60 fps, 1280×720 at 120 fps is its
other documented mode and still covers the 4x tracking view at 2.9 µm/px.

## 5. Steps, with your time, cash and calendar

Estimates. "You" is bench time or deciding time only Nick can do; code is
Claude sessions and not counted. Calendar is wall-clock from the start of
the step. Cash excludes tax and shipping and assumes Path B; Path A adds
$235 at step 3.

| # | Step | Your time | Cash | Calendar | Gate to the next step |
|---|------|-----------|------|----------|----------------------|
| 0 | Pond trip (§7), second jar, label both | 1–2 h | $0 (+$8 pipettes) | tomorrow | Jars on the sill, day 0 logged |
| 1 | G0 watch: side-light the jar daily; order slides + coverslips + well slides ($25) | 5 min/day | $25 | 5–10 days | Visible swimmers |
| 2 | G1: 30 s TOMLOV clips, `track.py`, tune `--min-area`; three clips where species cannot be told | 2–3 h | $0 | 1 week | G2 unlocked |
| 3 | G2 buy: used scope (§3), generic 0.5x adapter, LED kit, AR0234 USB 3, filament if low | 2–4 h of listing reading, 30 min ordering | $470–550 | 1–2 weeks shipping | Parts on the bench |
| 4 | G2 bring-up: `HARDWARE.md` §8 steps 1–6 (clean, LED, adapter, 60 fps, stop, light budget) | 1 day spread over a week | $0 | 1 week | Darkfield at 4x passes; 10x passes or falls back to oblique |
| 5 | G2 → G3: live `track.py` on the Studio feed, one unattended hour, ≥20 tracks > 5 s | 1 h to set up, an hour unattended | $0 | 2–3 days | G3 unlocked |
| 6 | G3 buy: stepper, TMC2209, coupler, 12 V supply | 15 min | $55–75 | 1 week | Parts on the bench |
| 7 | Print coupler + bracket (`cad/`), wire UART, hill-climb autofocus, 60 s hold at 10x | 1 day | $0 | 1–2 weeks | G4 plot |
| 8 | v3 geometry events, 48 h run on the Studio, first unattended clip | 1 h setup, 48 h unattended | $0 | 1 week | G5 unlocked |
| 9 | G5 buy: Pi 5 set + SSD; move the USB camera over; MJPEG-to-SSD soak | 1 day | ~$308 | 2 weeks | The dumb Pi runs alone |

**Totals.**

| Path | Your time | Cash | Calendar |
|------|-----------|------|----------|
| G0 + G1 only (steps 0–2) | ~1 day | $25–35 | 2–3 weeks |
| Through G4, Path B (steps 0–7) | ~4 days | $582–672 | 7–10 weeks |
| Through G4, Path A | ~4 days | $816–898 | 7–10 weeks (plus GS camera backorder) |
| Through G5 with the Pi, Path B (0–9) | ~5 days | ~$900–1,000 | 10–14 weeks |

The dominant delay is the used-scope hunt; start reading listings during
G0, buy at G2. The dominant cost is the scope; the second is the Pi, which
is why it moved to the end.

## 6. What is not verified and how to close it

- **eBay sold prices** for CH-2 / Alphaphot: eBay blocks readers. Open
  "Sold items" for `olympus ch-2 microscope` and `nikon alphaphot` in a
  browser (5 minutes). Asking prices above are from search summaries.
- **amscope.com prices** for RU050, T120B, DK-DRY100, PA4X: rate-limited.
  `curl https://amscope.com/products/<slug>.json` with slugs `ru050`,
  `c-t120`, `dk-dry100`, `pa4x-v300` once the IP cools, or a browser.
- **AR0234 B0495 frame rate at 1920×1200 over USB 3** and its exposure
  floor: Arducam's docs page blocked the reader. Check
  docs.arducam.com for B0495 before ordering; bring-up step 4 is the real
  test.
- **Nikon Alphaphot eyepiece and phototube diameters**: not found
  anywhere authoritative. Ask the seller (§3 question 4).
- **StepperOnline 11HS12-0674S** price and stock on omc-stepperonline.com:
  blocked. One browser visit; it halves the stepper line.
- **Pi GS camera stock at SparkFun**: page showed both "in stock" and
  "backorder". Only matters for Path A.
- **Kapton stack thickness**: an estimate from film plus adhesive. Measure
  a two-layer stack with calipers before trusting a 120 µm chamber claim.
- **Carolina residential delivery to Texas**: not stated. Phone, only if
  G0 fails.

## 7. Tomorrow: the pond trip

Zero purchases. Bring: two or three clean jars with lids, the turkey
baster, a paint strainer bag or a stocking, a marker and tape for labels,
a small cooler or a shaded bag (no direct sun on the jars in the car).

Where to sample, in order of yield for predators:

1. **Submerged plant stems and the undersides of floating leaves** in
   still, shallow water: squeeze a handful of plant material into a jar
   half full of its own water. This is the Paramecium, Stentor and rotifer
   source.
2. **Surface film in a sheltered corner** with the baster: scum is a
   bacterial mat and the grazers follow it.
3. **The top centimetre of sediment** from under 10–30 cm of water: a
   baster-full into the plant jar. Didinium and Dileptus live where the
   Paramecium are dense.
4. **Open water through the strainer** only if there is visible plankton
   (Daphnia, copepods); that goes in its own jar for the TOMLOV.

Rules: jars two-thirds full, lids loose, a few plant fragments left in,
one boiled rice grain per jar once home, windowsill with indirect light,
labelled with date and site. Day 1–3 clouds, day 5–10 glitters under a
side light, day 10–20 is predator time (`CLAUDE.md`, culture notes). Avoid
water with fuel sheen or algal paint-green blooms; those cultures crash.
Fill the sidecar fields now (date, source, site) so the clips inherit them.
