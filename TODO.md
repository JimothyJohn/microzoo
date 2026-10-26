# TODO

## Open questions for Nick

- 2026-10-25 MOG2 absorbs slow or paused swimmers into the background after ~`--history` frames (a sessile rotifer or a resting Paramecium vanishes from detection). Fine for G1; decide at v3 whether to add a static-blob detector or a long-history second subtractor.
- [ ] 2026-10-25 — **Tracker ID stability on ecosim clips** — track.py covers each Paramecium 0.87–0.94 of frames but the dominant ID holds only 0.17–0.42 (IDs break on avoidance reversals, swimmer bumps, debris merging into the blob). G1 asks for "stable IDs". `tests/test_cli_ecosim.py::test_tracker_follows_every_paramecium_through_the_debris` pins the current number.
  needs: a decision on whether scipy is acceptable on the Pi, or a pure-numpy assignment
  result: IDs survive reversals and bumps; G1 "stable IDs" becomes measurable in the sim before the jar delivers
  options: Hungarian via scipy | pure-numpy auction assignment (~30 lines) | velocity-aware birth suppression only | stitch offline in trackstats
  est: 3h
  difficulty: med
- [ ] 2026-10-25 — **Stentor contraction area threshold** — the sprite's contraction drops silhouette area ~55–65 %, not the 80 % the v3 rule in CLAUDE.md assumes (ball diameter = 0.25 × trumpet length is a sprite choice, not biology).
  needs: one real contraction on film, or a decision to keep 80 % until then
  result: v3 event rule and the sim agree on one number
  options: keep 80 % and wait for footage | lower the rule to 60 % | make the sprite ball smaller
  est: 30m
  difficulty: low
