# hardware/ — the microzoo rig, from jar to clip

Open `index.html` for the visual walkthrough (optical train, budget against
the $1,000 line, gate ladder, what is needed from Nick). The text files are
the engineering package.

| Path | What |
|------|------|
| `index.html` | Front page: rig at a glance, optical train, budget bars per gate, the two purchase paths, needed-from-you checklist |
| `HARDWARE.md` | Rig spec: what each part is for, optical numbers for both candidate sensors, light budget, capture and storage, Pi pin budget, bring-up checklist, open decisions |
| `bom.csv` | Cart-ready parts list, one row per purchasable item, grouped by the gate that unlocks it, with vendor part numbers, prices and stock as of 2026-10-25 and how each figure was checked |
| `SOURCING.md` | Where to buy, how to read a used-microscope listing, the Pi-first vs Studio-first fork, per-gate time/cash/calendar |
| `../cad/` | Printed parts (darkfield stop, focus coupler, LED carrier). Empty until G2; each file header names the dimension it was measured from |

## Status

- G0 in progress: jar collected 2026-10-25 (Bedford TX). Pond trip for a
  second jar planned for 2026-10-26; the field kit is the G0 group in
  `bom.csv` and costs nothing that is not already in the kitchen.
- Owned and counted at $0: TOMLOV TM3K-3D, Mac Studio, Bambu H2S.
- Nothing else bought. Every purchase row names its gate. G1 needs only
  slides and coverslips.

## Verification legend

*verified* = the vendor's own page was loaded on 2026-10-25 and the figure
read from it. *snapshot* = the figure came from a search summary, age
unknown. *estimate* = no vendor page, a round number. DigiKey, Mouser,
Amazon, Micro Center and arducam.com block automated readers, so every
figure from them is a snapshot; the part numbers are exact search strings.

## Note on the docs site

`docs/` is the published site; `hardware/index.html` is a standalone page
that loads two fonts from Google Fonts and nothing else. Open it from the
checkout or copy it under `docs/` if it should be public.
