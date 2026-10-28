# TODO

## Hand-offs for Nick

- [ ] 2026-10-26 — **Promote dev → master so the playground and docs/CNAME publish** — GitHub Pages serves master:/docs. The playground (docs/playground.html), the index card and docs/CNAME (microzoo.advin.io) sit on dev once the playground PR merges; nothing is live until master moves.
  needs: the playground PR merged into dev
  result: https://jimothyjohn.github.io/microzoo/playground.html is live and Pages knows the custom domain file
  est: 5m
  difficulty: low
  id: promote-dev-playground
  asked: 2026-10-26
  by: playground session
  notes: your merge, by hand (dev → master is never automated)
- [ ] 2026-10-26 — **DNS: microzoo.advin.io → GitHub Pages** — Route 53 CNAME in the advin.io zone (Z039212425BG1MHVPYWDN) pointing at jimothyjohn.github.io. UPSERT, waits for INSYNC, verifies at the zone's own name server.
  needs: aws CLI with Route 53 write access to advin.io
  result: `dig microzoo.advin.io CNAME` answers jimothyjohn.github.io
  est: 2m
  difficulty: low
  id: dns-microzoo-advin
  asked: 2026-10-26
  by: playground session
  notes: `! ./scripts/dns-microzoo-advin.sh`
- [ ] 2026-10-26 — **GitHub Pages custom domain + HTTPS** — sets the Pages cname to microzoo.advin.io through the API, then polls until GitHub has issued the certificate and switches https_enforced on (up to 30 min; re-run until it prints ok).
  needs: DNS in place, docs/CNAME on master
  result: https://microzoo.advin.io serves the site; the github.io URL redirects
  est: 5m plus the certificate wait
  difficulty: low
  depends: dns-microzoo-advin, promote-dev-playground
  id: pages-custom-domain
  asked: 2026-10-26
  by: playground session
  notes: `! ./scripts/pages-custom-domain.sh`
- [ ] 2026-10-27 — **Meca500 first contact through stage.py** — reads the pose, then a 100 µm XY square at 1 mm/s and back; never moves Z. Proves the TCP wiring and command strings against the real robot (the tests only ran against an emulator of the protocol).
  needs: Meca500 on the LAN (MECA_HOST, default 192.168.0.100), activated and homed, clear of the objective, no other client on port 10000; cell clear
  result: four "asked/got" lines and `meca-smoke: ok`; any `[1xxx]` error code means a command string is wrong and is worth pasting back
  est: 10m
  difficulty: low
  id: meca-smoke
  asked: 2026-10-27
  by: meca-stage session
  notes: `! MECA_HOST=<ip> ./scripts/meca-smoke.sh` (runs here; the robot is a LAN host)

- [ ] 2026-10-27 — **Measure and print the dish ring** — `cad/dish_ring.scad` (darkfield WS2812 ring + 60 × 15 mm dish riser for the TOMLOV) renders clean at working numbers (60 mm dish, IP67 tape 12 × 4.5 mm sleeve, 100/m); a cut-away preview lands in data/cad/dish_ring_section.png. Caliper numbers replace the working ones before printing.
  needs: calipers on the dish **base** (OD where it stands, floor thickness, foot recess, height), the TOMLOV lens nose diameter and backlight window, the strip sleeve width/thickness and LEDs per 10 cm; numbers into the top of the .scad (list in hardware/LED.md). OpenSCAD 2021.01 is still only on the DMG: drag it to /Applications
  result: STLs in data/cad/ for base, seat, stop and diffuser; print in matte black PLA (diffuser in white) and the dish's water sits 1 mm under the lens at bottom-out
  est: 1h
  difficulty: low
  id: dish-ring-print
  asked: 2026-10-27
  by: wave-psf session
  notes: `! ./scripts/cad-render.sh` (runs here); add `cad/dish_ring.scad meca_adapter` after MECA_BCD is measured

- [ ] 2026-10-28 — **Register an EcoTaxa account for the microzoo project** — v4 labels come from EcoTaxa (decided 2026-10-28). Accounts are approved by hand by the Villefranche team, so start the clock before G1 footage exists.
  needs: register at https://ecotaxa.obs-vlfr.fr/gui/register and wait for approval; then put the login in `.env` as ECOTAXA_USER / ECOTAXA_PASSWORD (gitignored, never committed)
  result: an approved account; task `ecotaxa-push-annotations` can create a private project and import the ecosim dry-run bundle
  est: 10m plus approval wait
  difficulty: low
  id: ecotaxa-account
  asked: 2026-10-28
  by: todo-answers session
  notes: web form, no script possible; the project is private

## Open questions for Nick

- [x] 2026-10-25 — **Slow or paused swimmers vanish from MOG2** — MOG2 absorbs a swimmer that stops or crawls into the background after ~`--history` frames (a sessile rotifer or a resting Paramecium drops out of detection). Fine for G1; the v3 event rules (Stentor contraction, anchored rotifers) need sessile blobs to persist.
      needs: a decision at v3, or a real clip showing it matters earlier
      result: sessile and paused organisms keep a track for the whole run
      options: static-blob detector on a long-exposure median | second MOG2 with a long history, OR the two masks | accept until v3
      est: 3h
      difficulty: med
      id: slow-swimmers-vanish-from-mog2
      asked: 2026-10-25
      by: track.py v1 session
      answer: accept until v3
      notes: 2026-10-27 the real clip arrived: a YouTube rotifer pausing in debris was absorbed by MOG2 in ~25 frames (5+ IDs). `track.py --bg hold` keeps it one ID (opt in, MOG2 still the default). An animal that never moves its own length is still invisible: that is the static-blob option, still v3.
      notes: accepted 2026-10-26; nothing changes in track.py until the v3 event work, where sessile blobs (Stentor, anchored rotifers) force the question
- [x] 2026-10-25 — **Tracker ID stability on ecosim clips** — track.py covers each Paramecium 0.87–0.94 of frames but the dominant ID holds only 0.17–0.42 (IDs break on avoidance reversals, swimmer bumps, debris merging into the blob). G1 asks for "stable IDs". `tests/test_cli_ecosim.py::test_tracker_follows_every_paramecium_through_the_debris` pins the current number.
  needs: a decision on whether scipy is acceptable on the Pi, or a pure-numpy assignment
  result: IDs survive reversals and bumps; G1 "stable IDs" becomes measurable in the sim before the jar delivers
  options: Hungarian via scipy | pure-numpy auction assignment (~30 lines) | velocity-aware birth suppression only | stitch offline in trackstats
  est: 3h
  difficulty: med
  answer: pure-numpy auction assignment (~30 lines)
  notes: done 2026-10-25 (`--assign auction`, default). On its own it moved stability 0.17–0.42 → 0.19–0.48; the diagnosis showed debris tracks stealing bodies and reversals outrunning the prediction, so an area gate (`--area-ratio 6`), blob-size birth suppression (`--fragment-scale 0.6`) and gating on the last measured position went in with it → 0.27–0.63. The rest is merge/split swaps, next item.
- [x] 2026-10-25 — **Stentor contraction area threshold** — the sprite's contraction drops silhouette area ~55–65 %, not the 80 % the v3 rule in CLAUDE.md assumes (ball diameter = 0.25 × trumpet length is a sprite choice, not biology).
  needs: one real contraction on film, or a decision to keep 80 % until then
  result: v3 event rule and the sim agree on one number
  options: keep 80 % and wait for footage | lower the rule to 60 % | make the sprite ball smaller
  est: 30m
  difficulty: low
  answer: keep 80 % and wait for footage
  notes: no change; the v3 rule stays at 80 % until a real contraction is on film
- [x] 2026-10-25 — **ID swaps when two swimmers merge into one blob** — with the assignment fixed, what still breaks ids on ecosim clips is a true merge: two Paramecia overlap for ~6 frames, one track takes the merged blob, the other goes unmatched, and at the split the ids come out swapped (seed 11, frames 52–58). Stability on that clip is 0.27–0.63; `tests/test_cli_ecosim.py` pins 0.25.
  needs: a choice of what continuity to trust through a merge
  result: ids survive crossings; G1 "stable IDs" holds on the sim, so the first real clip is judged on biology not tracker luck
  options: carry velocity through the merge (predict both, split by extrapolation) | appearance continuity (area, aspect, intensity histogram per track) | mark merged frames and stitch offline in trackstats | accept until real footage says how often it happens
  est: 4h
  difficulty: high
  depends: tracker-id-stability-on-ecosim-clips
  answer: carry velocity through the merge (predict both, split by extrapolation)
  notes: done 2026-10-26 (`--merge-ratio 1.5`, default; 0 disables). A matched blob ≥1.5× a track's own area with another track's extrapolation inside it forms a merge group; members coast on their own velocity, are not corrected with the shared centroid, and the split is assigned on the extrapolations. Clean on a head-on crossing (unit test). On the ecosim scenario it does not help (0.25–0.41): the 2D sim makes every overlap a bump, the Paramecium reverses inside the merge, and extrapolation picks the wrong body. Needs depth in the sim to measure; next item.
- [x] 2026-10-26 — **Give ecosim depth so swimmers can pass over each other** — the chamber is 100–200 µm deep and bodies are 50 µm thick, so most real crossings are pass-overs at different Z with no contact, which is exactly the case the merge rule in track.py is built for. The 2D sim turns every overlap into a bump (avoiding reaction), so the rule cannot be measured and the ID-stability number is pessimistic.
  needs: a Z coordinate per organism (uniform in the chamber depth, slow random walk), bumps only when |dz| < body thickness, and either no visual change or a mild defocus blur with |z − focal plane| (the focal-sweep 3D route in CLAUDE.md wants that anyway)
  result: ecosim clips with true pass-overs; `test_tracker_follows_every_paramecium_through_the_debris` measures the merge rule instead of the bump case; a defocus knob the autofocus work (v2) can reuse
  options: Z for collisions only, no visual effect | Z with defocus blur (sigma from |dz|, depth of field 10–50 µm per CLAUDE.md) | leave 2D and measure the merge rule on real footage at G1
  est: 3h
  difficulty: med
  depends: id-swaps-when-two-swimmers-merge-into-one-blob
  answer: Z with defocus blur (sigma from abs(dz), depth of field 10–50 µm per CLAUDE.md)
  notes: done 2026-10-26 (PR #12). `--depth 150 --dof 30 --focus depth/2`; Z uniform at spawn, 20 µm/√s random walk, sessile/anchored fixed, caught prey rides its predator. Bumps and strikes only when |dz| < mean thickness (new `Species.thick`, Paramecium ~51 µm). Per-body Gaussian defocus 0.1 µm sigma per µm beyond the DoF, far bodies drawn first; truth CSV gains `z_um`. `--depth 0` is bit-for-bit the old sim. Stability on the pinned seed 11 went 0.25–0.41 → 0.39–0.82 (floor raised 0.2 → 0.3); seeds 12–13 did not improve, so no trend claimed. New measurable: merge-group tracks coast ~45 µm off during long stacked pass-overs (median error 2.3 → 4.1 px on stacked frames), the next tracker number to attack.
- [x] 2026-10-25 — **Hardware path for G2: A or B?** — **A** Pi 5 + Pi Global Shutter Camera first (~$898 through G4; Pi 5 8 GB is $175 today and the GS camera is out of stock at 3 of 4 US resellers) or **B** USB 3 Arducam AR0234 C-mount into the Mac Studio for G2–G4, Pi bought at G5 (~$672 now, ~$980 after the Pi). `hardware/SOURCING.md` §4 recommends B. Not due until G2 passes; it decides $225 today and whether roadmap v1 "Pi capture" runs before or after v2–v3.
  needs: your pick, A or B
  result: bom.csv path column filtered, HARDWARE.md §9 updated, roadmap order in CLAUDE.md adjusted if B
  options: A (roadmap as written, dearer today) / B (recommended; Studio captures until G5)
  est: 5 min to decide
  difficulty: low
  depends: G2 deliverable (three clips where species can't be told)
  id: g2-hardware-path
  asked: 2026-10-25
  by: hardware BOM session
  answer: Focus on a used eBay option, I have a good scanner to look for good deals on nice equipment. Especially if it has a great resale value then I'll spend whatever I want on it.
  notes: done 2026-10-26. Neither A nor B: Path B's order (Studio through G4, Pi at G5) with the scope and camera sourced used via the scanner and resale value as the price rule. SOURCING.md §1/§4 rewritten with an eBay watchlist (BX/Eclipse stands, Basler/FLIR/Daheng USB3 cameras, what to check before paying), HARDWARE.md §2/§3/§9/§10 updated, bom.csv path column now both/floor/watch/pi with two watch rows, index.html cards, CLAUDE.md sourcing line. Camera sensor/SDK facts are flagged unverified in §6.
- [x] 2026-10-26 — **Label v4 crops on EcoTaxa instead of a home-grown tool?** — `ecotaxa.py export` now turns any tracked clip into an EcoTaxa import bundle (one object per track, several frames per object, the PlanktoScope morphometrics plus speed/turn/tortuosity columns). EcoTaxa gives a labelling UI, a random-forest classifier trained on those columns, and 700 M objects of prior art for free; the cost is an account (manual approval by the Villefranche team) and a public-or-private project of our clips. CLAUDE.md v4 says "YOLO fine-tune on own crops (~500 labeled)": the crops and labels could come out of EcoTaxa's export instead of a local labelling pass.
  needs: a yes/no on creating a microzoo project on ecotaxa.obs-vlfr.fr once G1 footage exists (register at /gui/register; manual approval), and whether the project is public
  result: v4 labelling happens in EcoTaxa; `ecotaxa.py` gains a `push` (API import) and an `annotations` (export labels back to the sidecar/track CSV) command; the ecosim bundles become the dry run
  options: yes, public project (shares the footage) | yes, private project | no, label locally (CVAT or a small Fable tool) and keep ecotaxa.py as an export only
  est: 2h for push + annotations once the account exists
  difficulty: low
  depends: G1 (real footage worth labelling)
  id: label-v4-on-ecotaxa
  asked: 2026-10-26
  by: ecotaxa bridge session
  notes: resolved in chat 2026-10-28: label on EcoTaxa. Public vs private not stated; going private (it can be opened later, not un-shared). CLAUDE.md v4 rewritten; account is hand-off `ecotaxa-account`, code is task `ecotaxa-push-annotations`
- [x] 2026-10-27 — **Retire "only Z is motorized" now the Meca500 holds the slide?** — CLAUDE.md's first two core decisions reject a motorized XY stage because moving the slide sloshes the chamber and the controller chases its own disturbance. `stagesim.py table` puts numbers on that: a sealed 150 µm spacer chamber relaxes viscously in 2.3 ms and its closed walls forbid net flow, so the water rides the slide; only an open well (≈100 ms lag plus surface waves) sloshes. The arm also replaces the G3 Z stepper. What the sim cannot settle without the rig: acceleration limit, the arm's flex mode and standstill jitter (all assumed), and whether 5 µm repeatability is good enough for Z at 10x (45% of an 11 µm depth of field) and 40x (3× its 1.5 µm).
  needs: a decision; ideally after meca-smoke and a tracked-particle jitter/settle measurement on the rig
  result: CLAUDE.md core decisions and gate table rewritten around the arm (XY follow + Z focus on one device, sealed chambers only), or kept with the arm as a slow re-centre/survey tool
  options: arm is the stage: rewrite the decisions | arm for survey + open-loop re-centre only, digital tracking stays primary | wait for jitter/settle numbers
  est: 30m for the CLAUDE.md rewrite
  difficulty: low
  depends: meca-smoke
  id: retire-z-only-decision
  asked: 2026-10-27
  by: meca-stage session
  notes: resolved in chat 2026-10-28: retire it, ahead of meca-smoke. CLAUDE.md now has "the Meca500 is the stage" (XY follow + Z focus, sealed chambers only), G3 unlocks nothing to buy, NEMA 11/TMC2209 dropped from Tier 1 and v2. Sim's accel/flex/jitter stay flagged as assumptions until measured. Site and hardware/ still say stepper: task `arm-is-stage-docs`
- [x] 2026-10-27 — **Which LEDs is the strand: WS2812B tape or 12 mm bullet pixels?** — the dish ring is drawn for tape on a conical land under the dish. A 12 mm bullet pixel needs ~11.5 mm of height aimed that shallow and there is 10.4 mm under the seat (the dish floor has to sit at 14.9 mm for the 17.91 mm lens bottom-out), so bullets need a different layout: pixels outside the dish aimed down-and-in through a side window.
  needs: a look at the strand (flat tape with LEDs on it, or round 12 mm pixels on wire), and LEDs per metre if tape
  result: tape: print as drawn after measuring; bullets: I redraw the ring around them
  options: tape 60/m | tape 144/m | tape 30/m | 12 mm bullet pixels
  est: 2m
  difficulty: low
  id: led-strip-type
  asked: 2026-10-27
  by: wave-psf session
  notes: resolved in chat 2026-10-27: IP67 WS2812B tape, ~100/m (Nick's estimate, unmeasured); ring redrawn for the sleeve with a 30° land tilt

## Tasks

- [ ] 2026-10-27 — **Tune the tracker on the first TOMLOV clips, then decide the default background** — `--bg hold` beat MOG2 on every YouTube clip and on ecosim, but its thresholds (`--thresh 9`, `--hold-edge 2`) were set on third-party footage. Nick (2026-10-27): make it the default only after it is tuned on his own setup.
  needs: G1 footage: 30 s TOMLOV clips of the Bedford jar with sidecars in data/
  result: thresholds chosen on our own sensor and illumination; `--bg hold` default (or a reason not to); the clips added to the real-footage tests
  est: 3h
  difficulty: med
  id: tune-bg-on-tomlov
  asked: 2026-10-27
  by: bg-hold session
  notes: start from `uv run python track.py data/<clip>.mp4 --bg hold` vs `--bg mog2`; sweep `--thresh` 9, 16, 36 and `--hold-edge` 0, 1, 2; judge by eye on `_tracks.mp4`, not by track count
- [ ] 2026-10-28 — **`ecotaxa.py push` and `annotations`** — import a bundle into a private EcoTaxa project over the API, and pull validated labels back into the sidecar / track CSV. Dry run on ecosim bundles; real run on G1 clips.
  needs: an approved account (ecotaxa-account); the API calls checked against EcoTaxa's published OpenAPI spec, not memory
  result: v4 labelling loop closes: track → export → push → label on EcoTaxa → annotations → YOLO training set
  est: 2h
  difficulty: low
  depends: ecotaxa-account
  id: ecotaxa-push-annotations
  asked: 2026-10-28
  by: todo-answers session
- [ ] 2026-10-28 — **Carry "the arm is the stage" into the site and hardware docs** — CLAUDE.md retired "only Z is motorized" on 2026-10-28, but docs/index.html (lede meta, the slosh paragraph, G3 row, signal-path SVG "Z stepper on fine focus", v2 text, BOM checklist, "rejected: motorized XY stage") and hardware/ (HARDWARE.md Z-axis sections and Pi pinout, bom.csv rows 3.1–3.5, SOURCING.md stepper rows and step 6) still describe the knob stepper.
  needs: nothing
  result: the public site and the BOM agree with CLAUDE.md; stepper rows removed or marked retired
  est: 1h
  difficulty: low
  id: arm-is-stage-docs
  asked: 2026-10-28
  by: todo-answers session
