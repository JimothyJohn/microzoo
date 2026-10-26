# TODO

## Open questions for Nick

- 2026-10-25 MOG2 absorbs slow or paused swimmers into the background after ~`--history` frames (a sessile rotifer or a resting Paramecium vanishes from detection). Fine for G1; decide at v3 whether to add a static-blob detector or a long-history second subtractor.
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
- [ ] 2026-10-26 — **Give ecosim depth so swimmers can pass over each other** — the chamber is 100–200 µm deep and bodies are 50 µm thick, so most real crossings are pass-overs at different Z with no contact, which is exactly the case the merge rule in track.py is built for. The 2D sim turns every overlap into a bump (avoiding reaction), so the rule cannot be measured and the ID-stability number is pessimistic.
  needs: a Z coordinate per organism (uniform in the chamber depth, slow random walk), bumps only when |dz| < body thickness, and either no visual change or a mild defocus blur with |z − focal plane| (the focal-sweep 3D route in CLAUDE.md wants that anyway)
  result: ecosim clips with true pass-overs; `test_tracker_follows_every_paramecium_through_the_debris` measures the merge rule instead of the bump case; a defocus knob the autofocus work (v2) can reuse
  options: Z for collisions only, no visual effect | Z with defocus blur (sigma from |dz|, depth of field 10–50 µm per CLAUDE.md) | leave 2D and measure the merge rule on real footage at G1
  est: 3h
  difficulty: med
  depends: id-swaps-when-two-swimmers-merge-into-one-blob
- 2026-10-25 Hardware path for G2: **A** Pi 5 + Pi Global Shutter Camera first (~$898 through G4; Pi 5 8 GB is $175 today and the GS camera is out of stock at 3 of 4 US resellers) or **B** USB 3 Arducam AR0234 C-mount into the Mac Studio for G2–G4, Pi bought at G5 (~$672 now, ~$980 after the Pi). `hardware/SOURCING.md` §4 recommends B. Not due until G2 passes; it decides $225 today and whether roadmap v1 "Pi capture" runs before or after v2–v3.
  needs: your pick, A or B
  result: bom.csv path column filtered, HARDWARE.md §9 updated, roadmap order in CLAUDE.md adjusted if B
  options: A (roadmap as written, dearer today) / B (recommended; Studio captures until G5)
  est: 5 min to decide
  difficulty: low
  depends: G2 deliverable (three clips where species can't be told)
