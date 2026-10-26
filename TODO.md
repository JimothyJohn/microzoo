# TODO

## Open questions for Nick

- 2026-10-25 No GitHub remote yet. Want `gh repo create JimothyJohn/microzoo` plus the repo-baseline wiring (CI gate, Dependabot, auto-merge, `dev`)? Nothing pushed until you say.
- 2026-10-25 MOG2 absorbs slow or paused swimmers into the background after ~`--history` frames (a sessile rotifer or a resting Paramecium vanishes from detection). Fine for G1; decide at v3 whether to add a static-blob detector or a long-history second subtractor.
- 2026-10-25 Hardware path for G2: **A** Pi 5 + Pi Global Shutter Camera first (~$898 through G4; Pi 5 8 GB is $175 today and the GS camera is out of stock at 3 of 4 US resellers) or **B** USB 3 Arducam AR0234 C-mount into the Mac Studio for G2–G4, Pi bought at G5 (~$672 now, ~$980 after the Pi). `hardware/SOURCING.md` §4 recommends B. Not due until G2 passes; it decides $225 today and whether roadmap v1 "Pi capture" runs before or after v2–v3.
  needs: your pick, A or B
  result: bom.csv path column filtered, HARDWARE.md §9 updated, roadmap order in CLAUDE.md adjusted if B
  options: A (roadmap as written, dearer today) / B (recommended; Studio captures until G5)
  est: 5 min to decide
  difficulty: low
  depends: G2 deliverable (three clips where species can't be told)
