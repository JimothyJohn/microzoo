# TODO

## Open questions for Nick

- [ ] 2026-10-25 — **Slow or paused swimmers vanish from MOG2** — MOG2 absorbs a swimmer that stops or crawls into the background after ~`--history` frames (a sessile rotifer or a resting Paramecium drops out of detection). Fine for G1; the v3 event rules (Stentor contraction, anchored rotifers) need sessile blobs to persist.
      needs: a decision at v3, or a real clip showing it matters earlier
      result: sessile and paused organisms keep a track for the whole run
      options: static-blob detector on a long-exposure median | second MOG2 with a long history, OR the two masks | accept until v3
      est: 3h
      difficulty: med
      id: slow-swimmers-vanish-from-mog2
      asked: 2026-10-25
      by: track.py v1 session
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
- [ ] 2026-10-25 — **ID swaps when two swimmers merge into one blob** — with the assignment fixed, what still breaks ids on ecosim clips is a true merge: two Paramecia overlap for ~6 frames, one track takes the merged blob, the other goes unmatched, and at the split the ids come out swapped (seed 11, frames 52–58). Stability on that clip is 0.27–0.63; `tests/test_cli_ecosim.py` pins 0.25.
  needs: a choice of what continuity to trust through a merge
  result: ids survive crossings; G1 "stable IDs" holds on the sim, so the first real clip is judged on biology not tracker luck
  options: carry velocity through the merge (predict both, split by extrapolation) | appearance continuity (area, aspect, intensity histogram per track) | mark merged frames and stitch offline in trackstats | accept until real footage says how often it happens
  est: 4h
  difficulty: high
  depends: tracker-id-stability-on-ecosim-clips
- [ ] 2026-10-25 — **Hardware path for G2: A or B?** — **A** Pi 5 + Pi Global Shutter Camera first (~$898 through G4; Pi 5 8 GB is $175 today and the GS camera is out of stock at 3 of 4 US resellers) or **B** USB 3 Arducam AR0234 C-mount into the Mac Studio for G2–G4, Pi bought at G5 (~$672 now, ~$980 after the Pi). `hardware/SOURCING.md` §4 recommends B. Not due until G2 passes; it decides $225 today and whether roadmap v1 "Pi capture" runs before or after v2–v3.
  needs: your pick, A or B
  result: bom.csv path column filtered, HARDWARE.md §9 updated, roadmap order in CLAUDE.md adjusted if B
  options: A (roadmap as written, dearer today) / B (recommended; Studio captures until G5)
  est: 5 min to decide
  difficulty: low
  depends: G2 deliverable (three clips where species can't be told)
  id: g2-hardware-path
  asked: 2026-10-25
  by: hardware BOM session
