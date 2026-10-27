# Microcosmos Tracker

Automated filming and tracking of pond microorganisms for an educational series: predator/prey ecology at the scale of a drop of water. The rig watches a still chamber for hours, tracks every swimmer in software, auto-clips interesting events, and later classifies species. Think Planet Earth, microscopic.

Owner: Nick. Background: EE, motion control, embedded, CAD, 3D printing (Bambu H2S), Mac Studio for heavy compute. Assume competence; skip hand-holding. Be direct, lead with problems, keep prose short, explain reasoning on code.

## Core design decisions (do not relitigate without new evidence)

- **Digital tracking, not a motorized XY stage.** Moving the stage sloshes the chamber; the organism rides the water; the controller chases its own disturbance. Instead: low magnification on a global-shutter sensor, track every blob, crop a follow-window in software. Zero lag, many targets at once.
- **Only Z is motorized.** Autofocus on image sharpness (variance of Laplacian), slow PID with a deadband wider than depth of field, rate-limited so the image never visibly breathes.
- **Darkfield, not phase contrast.** Transparent protists glow on black at 4x–10x with a $20 condenser stop. Phase is a 10x-and-up feature costing $500+ more. Oblique illumination is the fallback if darkfield at 10x is too dim.
- **Contrast beats magnification.** Working magnification is 4x (tracking view, ~3 mm field) and 10x (follow view, ~1 mm field). 40x is for stationary subjects only.
- **Keep the Pi dumb.** Capture, detect, track, clip, focus run on the Pi 5 deterministically. Anything needing a model or a second look runs on the Mac Studio over the network.
- **Sample chamber matters more than optics.** 100–200 µm spacer-tape chamber or a well slide, vaseline-sealed, LED only (halogen cooks samples and causes convection that reads as drift). No methylcellulose for ecology footage; it changes behavior.
- **Tilt/roll does not give 3D** at these scales (DoF 10–50 µm vs 150 µm chamber; no perspective in a microscope image). 3D routes are focal sweep (free, uses the Z motor) and lensless digital holography (side rig, ~$60). Light-field and stereo rejected.
- **PlanktoScope rejected** as the primary instrument: it's a flow-through census imager, nothing hunts anything. Possibly a v4 species-count layer.

## Gates (purchases are unlocked by deliverables, never by enthusiasm)

| Gate | Deliverable | Unlocks |
|---|---|---|
| G0 Culture | Jar of local pond water + one grain of rice/wheat, alive 10 days, visible swimmers | Nothing. Precondition for everything. |
| G1 Tracker on TOMLOV | Real organisms under the owned TOMLOV TM3K-3D (backlit, top light off), `track.py` produces `_tracks.mp4` with stable IDs, a CSV, and a follow clip worth watching | Nothing yet |
| G2 Resolution ceiling | Three clips where something clearly happened but species can't be told | Used trinocular compound scope (Olympus CH-2/CH30, Nikon Alphaphot), then Pi 5 + global-shutter cam + 0.5x C-mount reducer |
| G3 One hour tracked | Unattended 60 fps hour, ≥20 tracks >5 s | Z stepper (NEMA 11 + TMC2209) |
| G4 Autofocus holds | Swimming Paramecium at 10x held 60 s, sharpness-vs-time plot | Event detection work |
| G5 First unattended capture | 48 h run files a predator/prey clip nobody watched happen | Tier 2 camera, focal-sweep 3D, holography side rig |

Current status: G0 in progress (sample collected 2026-10-25, Bedford TX park). TOMLOV owned. Nothing purchased.

## Hardware

Owned: TOMLOV TM3K-3D digital scope (reflected/backlit, ~10–20 µm resolution floor, HDMI/USB out; good for Daphnia/copepods/rotifers, cannot resolve ciliate anatomy), Bambu H2S, Mac Studio, robots/motion control gear.

Tier 1 target (~$560–730): used trinoc compound scope $300–450; darkfield stops printed; 23.2 mm→C-mount 0.5x reducer $40–75; 3–5 W LED + CC driver $25–40; Pi 5 8 GB kit ~$110; Arducam AR0234 2.3 MP global shutter ~$100 (or official Pi GS cam IMX296 ~$50); NEMA 11 + TMC2209 + printed coupler ~$40; chamber consumables ~$30.

Tier 2 only if cropping bites: 5–12 MP USB3 global-shutter machine-vision cam (Daheng/Basler/FLIR) into the Mac Studio, $300–600.

Sourcing policy (Nick, 2026-10-26): scope and camera come used off eBay through Nick's deal scanner; parts with strong resale value (Olympus BX / Nikon Eclipse class stands, Basler/FLIR cameras) have no budget ceiling, so a Tier 2 camera is fair at G2 if it comes used. The gate ladder still decides *when*. Watchlist: `hardware/SOURCING.md` §4.

Key numbers (AR0234, 3 µm px, 1920 wide, 0.5x reducer): 4x → 1.5 µm/px, 2.9×1.8 mm field, Paramecium at 1 mm/s = 11 px/frame at 60 fps. 10x → 0.6 µm/px, 1.15×0.7 mm. Keep exposure ≤2 ms for ≤1 px motion blur.

## Software

`track.py` (v1, exists, tested on synthetic data): MOG2 background subtraction → morphology → contours → per-track constant-velocity Kalman → greedy nearest-neighbour assignment. Outputs `<stem>_tracks.mp4`, `<stem>_tracks.csv`, `<stem>_follow_<id>.mp4`. Knobs: `--min-area` (the one you'll actually turn), `--thresh`, `--history`, `--max-dist`, `--min-life`, `--scale` (detect on downscaled frame, crop from full-res; use 0.5 on the Pi at 1080p). Known weakness: greedy assignment swaps IDs when swimmers cross; fix is `scipy.optimize.linear_sum_assignment`, left out to avoid a scipy dep on the Pi.

Roadmap:
- v1 Pi capture: `picamera2` 1920×1200 @ 60 fps, 2 ms exposure, ring buffer; same pipeline live.
- v2 Autofocus: Laplacian variance on the follow-crop, TMC2209 over UART, PID + deadband, hill-climb on startup, ~2 µm/s rate limit.
- v3 Events from geometry alone (no ML): two tracks converge and one vanishes = capture; sessile blob area drops 80% in one frame = Stentor contraction. Trigger 10 s pre-roll clips. Subtract per-frame median motion of all tracks before calling anything "swimming" (convection). Optional single open-loop stage nudge to re-center a target near frame edge during an event; not a servo.
- Sim food chain (exists): every species carries `prey` + `prey_ratio`; one feeding path (graze in a frame, or capture/ingest/digest) serves swimmers, hunters, sessile bells and traps (heliozoa, Hydra). `ecosim.py --preset` picks the rung; `species.food_web()` lists the edges.
- v4 Species: YOLO fine-tune on own crops (~500 labeled), runs offline on Mac Studio. Ecology dashboard: who eats whom, encounter rates, speed distributions. Optional PlanktoScope census layer.
- 3D: focal sweep (Z ramp 10–20 Hz, sharpness-per-track gives Z), then lensless holography (bare sensor + point LED, Fresnel back-propagation).

Site: `docs/` is published by GitHub Pages from `master:/docs` at https://microzoo.advin.io (Route 53 CNAME + Pages custom domain, scripts in `scripts/`). `docs/playground.html` is the interactive sim: a JS port of the ecosim behaviours over the darkfield sprite atlas, per-species colour, Z defocus as a mipmap bias against a focus plane, additive glow; `?preset=hunt&hud=1&focus=60&dof=20&t=15` is a shareable state. Keep its numbers equal to `species.py` when those change.

## Biology cheat sheet

| Organism | Role | Size | Notes |
|---|---|---|---|
| Paramecium | prey/grazer | 120–300 µm, ~1 mm/s | benchmark tracking target, spiral path |
| Didinium | predator of Paramecium | 80–200 µm | barrel, two cilia belts, strike takes seconds; headline footage |
| Lacrymaria olor | predator | 100 µm body, neck to 1 mm | neck whips in ms; needs fps not mag |
| Dileptus | predator | 200–500 µm, slow | trunk sweeps; easy to track |
| Rotifers | filter feeder | 100–500 µm | often anchored; "wheels" are a strong motion signature |
| Stentor | filter feeder | 0.5–2 mm | sessile, contracts in ~10 ms |
| Amoeba | engulfer | 100–500 µm | timelapse only |
| Hydra | top predator | 1–10 mm | eats Daphnia; needs deep chamber |
| Daphnia/copepods | big prey | 1–3 mm | jump 10+ mm/s; TOMLOV territory |

Rungs below and above that cast, all in `species.py` with prey lists (`ecosim.py --preset microbe|ciliate|metazoan` sets the cast and µm/px for each view):

| Organism | Tier | Role | Size | Notes |
|---|---|---|---|---|
| Bacteria | microbe | base of the chain | 2–5 µm | run-and-tumble; a point at 4x, needs 40x |
| Chlamydomonas | microbe | alga, grazed | 10–15 µm | two flagella, jerky breaststroke |
| Euglena | microbe | flagellate, grazed | 50–70 µm | one flagellum, red eyespot, corkscrews |
| Diatom | microbe | alga, grazed | 20–100 µm | glass pillbox, glides on the glass |
| Tetrahymena | ciliate | bacterivore, prey | 40–60 µm | the lab bacterivore; Coleps, Lacrymaria, Dileptus take it |
| Halteria | ciliate | bacterivore, prey | 25–35 µm | jumping ciliate: 10 body lengths in one frame |
| Coleps | ciliate | predator / scavenger | 50–80 µm | armoured barrel, takes small ciliates whole |
| Euplotes | ciliate | bacterivore, crawler | 80–150 µm | walks on cirri over the glass, stop-start |
| Blepharisma | ciliate | prey/grazer | 100–200 µm | pink slipper, slower than Paramecium |
| Vorticella | ciliate | sessile bacterivore | 60 µm bell, 250 µm stalk | stalk coils in ms, re-extends in s |
| Spirostomum | ciliate | giant grazer | 1–3 mm | worm-like, snaps to a quarter length when touched |
| Actinosphaerium | ciliate | sessile predator | 200–500 µm | heliozoan sun; swimmers stick to its rays |
| Volvox | ciliate | colonial alga | 300–500 µm | rolling hollow sphere |
| Cyclops | metazoan | predator (copepod) | ~1 mm | hops, grabs rotifers and ciliates |
| Ostracod | metazoan | grazer (seed shrimp) | 0.5–1 mm | two valves, steady swimmer |
| Nematode | metazoan | grazer (roundworm) | 0.5–1 mm | S-curve thrash; Hydra and planarians take it |
| Tardigrade | metazoan | grazer (water bear) | 300–500 µm | eight legs, clambers over debris |
| Gastrotrich | metazoan | bacterivore | 100–300 µm | bowling-pin glider |
| Planaria | metazoan | predator (flatworm) | 3–10 mm | glides on cilia, takes worms and rotifers |

Culture: still water + submerged plant squeezings + sediment + surface film, two-thirds full, lid loose, one boiled rice/wheat grain, windowsill. Bacteria bloom days 1–3 (cloudy, sulfur smell), Paramecium bloom days 5–10 (glittering cloud under side light), predators days 10–20. Milky white = overfed; pour half, top up with pond water.

## Working conventions

- Prototype on the Mac Studio, deploy to the Pi. Pin versions in `requirements.txt`; no scipy on the Pi unless unavoidable.
- Every clip gets a sidecar: date, source jar, chamber depth, objective, illumination, exposure, fps. Future dataset labels depend on it.
- Save raw full-frame video plus track CSV; follow crops and event clips are derived and regenerable.
- Printed parts live in `cad/` as OpenSCAD or exported STEP with the parametrized dimension noted (condenser tray diameter, fine-focus knob diameter).
- Don't propose purchases. If a task seems to need hardware not yet unlocked, say which gate unlocks it and find the no-purchase path.
- Deliverables for Nick: scannable top layer, details collapsible or in sections he can skip. He stops reading long outputs.

## References

- Journey to the Microcosmos (YouTube) for what good footage looks like; "Didinium: The Paramecium Hunter" is the target shot.
- Cell Image Library: Didinium nasutum capture sequence, frame by frame.
- Robert Berdan, canadiannaturephotographer.com: darkfield pond life, collecting technique.
- Stanford Prakash lab Gravity Machine / Squid: the closed-loop tracking reference.
- OpenFlexure v7: the open motorized-stage alternative, not chosen.
- TrackMate (Fiji): offline tracking reference and output style.
