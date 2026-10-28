# Microcosmos Tracker

Automated filming and tracking of pond microorganisms for an educational series: predator/prey ecology at the scale of a drop of water. The rig watches a still chamber for hours, tracks every swimmer in software, auto-clips interesting events, and later classifies species. Think Planet Earth, microscopic.

Owner: Nick. Background: EE, motion control, embedded, CAD, 3D printing (Bambu H2S), Mac Studio for heavy compute. Assume competence; skip hand-holding. Be direct, lead with problems, keep prose short, explain reasoning on code.

## Core design decisions (do not relitigate without new evidence)

- **The Meca500 is the stage: XY follow and Z focus on one device** (Nick, 2026-10-28; replaces "digital tracking, not a motorized XY stage" and "only Z is motorized"). The slosh argument holds only for open wells: a sealed 150 µm spacer chamber relaxes viscously in 2.3 ms and its walls forbid net flow, so the water rides the slide (`stagesim.py table`). Software still tracks every blob at low magnification on a global-shutter sensor; the arm jogs the slide to keep the chosen target in the field (~50 ms latency, Paramecium lags ~140 px at 10x), and the digital follow-crop rides on top for zero-lag framing. Bursts (Halteria hops, Cyclops/Daphnia jumps) are lost at 10x: widen the view, don't chase. Not yet measured: acceleration limit, flex mode, standstill jitter; `stage.py`'s `SimParams` are assumptions until `meca-smoke` and a tracked-particle settle/jitter clip replace them.
- **Autofocus drives the arm's Z.** Image sharpness (variance of Laplacian), slow PID with a deadband wider than depth of field, rate-limited so the image never visibly breathes. 5 µm repeatability is 7% of the 4x DoF and 45% of the 10x DoF: fine for holding focus; 40x Z-stacks need step accuracy measured on the rig. The fine-focus-knob stepper is retired.
- **Darkfield, not phase contrast.** Transparent protists glow on black at 4x–10x with a $20 condenser stop. Phase is a 10x-and-up feature costing $500+ more. Oblique illumination is the fallback if darkfield at 10x is too dim.
- **Contrast beats magnification.** Working magnification is 4x (tracking view, ~3 mm field) and 10x (follow view, ~1 mm field). 40x is for stationary subjects only.
- **Keep the Pi dumb.** Capture, detect, track, clip, focus run on the Pi 5 deterministically. Anything needing a model or a second look runs on the Mac Studio over the network.
- **Sample chamber matters more than optics.** 100–200 µm spacer-tape chamber, vaseline-sealed (sealed is mandatory now the slide moves; open wells slosh and are for static shots only), LED only (halogen cooks samples and causes convection that reads as drift). No methylcellulose for ecology footage; it changes behavior.
- **Tilt/roll does not give 3D** at these scales (DoF 10–50 µm vs 150 µm chamber; no perspective in a microscope image). 3D routes are focal sweep (free, uses the arm's Z) and lensless digital holography (side rig, ~$60). Light-field and stereo rejected.
- **PlanktoScope rejected** as the primary instrument: it's a flow-through census imager, nothing hunts anything. Possibly a v4 species-count layer.

## Gates (purchases are unlocked by deliverables, never by enthusiasm)

| Gate | Deliverable | Unlocks |
|---|---|---|
| G0 Culture | Jar of local pond water + one grain of rice/wheat, alive 10 days, visible swimmers | Nothing. Precondition for everything. |
| G1 Tracker on TOMLOV | Real organisms under the owned TOMLOV TM3K-3D (backlit, top light off), `track.py` produces `_tracks.mp4` with stable IDs, a CSV, and a follow clip worth watching | Nothing yet |
| G2 Resolution ceiling | Three clips where something clearly happened but species can't be told | Used trinocular compound scope (Olympus CH-2/CH30, Nikon Alphaphot), then Pi 5 + global-shutter cam + 0.5x C-mount reducer |
| G3 One hour tracked | Unattended 60 fps hour, ≥20 tracks >5 s | Nothing to buy: the owned Meca500 replaces the Z stepper |
| G4 Autofocus holds | Swimming Paramecium at 10x held 60 s, sharpness-vs-time plot | Event detection work |
| G5 First unattended capture | 48 h run files a predator/prey clip nobody watched happen | Tier 2 camera, focal-sweep 3D, holography side rig |

Current status: G0 in progress (sample collected 2026-10-25, Bedford TX park). TOMLOV owned. Nothing purchased.

## Hardware

Owned: TOMLOV TM3K-3D digital scope (reflected/backlit, ~10–20 µm resolution floor, HDMI/USB out; good for Daphnia/copepods/rotifers, cannot resolve ciliate anatomy), Bambu H2S, Mac Studio, Meca500 R3 arm (holds the slide; `stage.py`, text API over TCP 10000), robots/motion control gear.

Tier 1 target (~$520–690): used trinoc compound scope $300–450; darkfield stops printed; 23.2 mm→C-mount 0.5x reducer $40–75; 3–5 W LED + CC driver $25–40; Pi 5 8 GB kit ~$110; Arducam AR0234 2.3 MP global shutter ~$100 (or official Pi GS cam IMX296 ~$50); chamber consumables ~$30.

Tier 2 only if cropping bites: 5–12 MP USB3 global-shutter machine-vision cam (Daheng/Basler/FLIR) into the Mac Studio, $300–600.

Sourcing policy (Nick, 2026-10-26): scope and camera come used off eBay through Nick's deal scanner; parts with strong resale value (Olympus BX / Nikon Eclipse class stands, Basler/FLIR cameras) have no budget ceiling, so a Tier 2 camera is fair at G2 if it comes used. The gate ladder still decides *when*. Watchlist: `hardware/SOURCING.md` §4.

Key numbers (AR0234, 3 µm px, 1920 wide, 0.5x reducer): 4x → 1.5 µm/px, 2.9×1.8 mm field, Paramecium at 1 mm/s = 11 px/frame at 60 fps. 10x → 0.6 µm/px, 1.15×0.7 mm. Keep exposure ≤2 ms for ≤1 px motion blur.

## Software

`track.py` (v1, exists, tested on synthetic data): MOG2 background subtraction → morphology → contours → per-track constant-velocity Kalman → global assignment (pure-numpy auction; `--assign greedy` is the old nearest-neighbour). Outputs `<stem>_tracks.mp4`, `<stem>_tracks.csv`, `<stem>_follow_<id>.mp4`. Knobs: `--min-area` (the one you'll actually turn), `--thresh`, `--history`, `--max-dist`, `--min-life`, `--scale` (detect on downscaled frame, crop from full-res; use 0.5 on the Pi at 1080p). Background: `--bg mog2` (default) forgets a swimmer that pauses within ~25 frames on real footage; `--bg hold` seeds from a median, never learns under a track that has proven it moves, and models edge jitter, so a pausing rotifer keeps one ID (`--thresh 36` on compression-smoothed footage). Real-footage regressions: `scripts/real-clips.sh` + `pytest --real-clips=data/real`. Known weaknesses: swimmers that cross can still swap IDs (the auction stops neighbours stealing detections, not identical bodies trading places); an animal that never moves its own length is invisible to either background model.

Roadmap:
- v1 Pi capture: `picamera2` 1920×1200 @ 60 fps, 2 ms exposure, ring buffer; same pipeline live.
- v2 Autofocus: Laplacian variance on the follow-crop, Z through `stage.py` (Meca500), PID + deadband, hill-climb on startup, ~2 µm/s rate limit.
- v3 Events from geometry alone (no ML): two tracks converge and one vanishes = capture; sessile blob area drops 80% in one frame = Stentor contraction. Trigger 10 s pre-roll clips. Subtract per-frame median motion of all tracks before calling anything "swimming" (convection). Keeping the target in the field is the arm's follow loop (`stagesim.py run --mode follow`), not the event layer.
- Sim food chain (exists): every species carries `prey` + `prey_ratio`; one feeding path (graze in a frame, or capture/ingest/digest) serves swimmers, hunters, sessile bells and traps (heliozoa, Hydra). `ecosim.py --preset` picks the rung; `species.food_web()` lists the edges.
- v4 Species: crops labelled on EcoTaxa (private project, Nick 2026-10-28; `ecotaxa.py` gains `push` and `annotations` once the account exists), then YOLO fine-tune on those labels (~500), offline on the Mac Studio. Ecology dashboard: who eats whom, encounter rates, speed distributions. Optional PlanktoScope census layer.
- EcoTaxa bridge (exists): `ecotaxa.py export` turns a tracked clip into an EcoTaxa import bundle (one object per track, several frames per object, the 33 PlanktoScope morphometrics on OpenCV with scikit-image semantics, plus speed/turn/tortuosity columns); `ecotaxa.py pull` reads public projects. Reference: project 2748, the original PlanktoScope dataset (`references/ecotaxa_2748_summary.json`). v4 labelling happens on EcoTaxa's UI and classifier.
- 3D: focal sweep (Z ramp 10–20 Hz, sharpness-per-track gives Z), then lensless holography (bare sensor + point LED, Fresnel back-propagation).
- Sim optics + multi-focal (exists): `optics.py` is a wave-optics defocus PSF from NA/immersion/λ (Airy in focus, ringed disc with OTF zeros out of it); `ecosim.py --na --planes N --plane-spacing` renders N synchronised cameras plus an all-in-focus oracle; `edof.py` fuses by per-pixel selection (no synthesised detail) and gives Z per body, scored against truth. Use it to size a beam-splitter rig before buying one. Learned EDOF that fills detail at OTF zeros is a prior, not a measurement; label it if it ever ships in footage.

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
