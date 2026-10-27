# microzoo

Automated filming and tracking of pond microorganisms. Full brief, design
decisions, gates and roadmap: [CLAUDE.md](CLAUDE.md).

## Quickstart (Mac Studio)

```sh
make install-dev   # uv sync --locked
make test-all      # unit + synthetic end-to-end
make demo          # synthetic swimmers -> data/demo_tracks.mp4, _tracks.csv, _follow_<id>.mp4
```

Track a real clip:

```sh
uv run python track.py data/2026-10-25_jarA_4x.mp4 --min-area 30
```

Outputs land next to the input (or `--out-dir`):

| File | What |
|---|---|
| `<stem>_tracks.mp4` | boxes, IDs and trails for every confirmed track |
| `<stem>_tracks.csv` | `frame,t,track_id,x,y,area,w,h`, full-res pixels |
| `<stem>_follow_<id>.mp4` | 256 px crop riding the longest track (`--follow <id>` to pick) |
| `<stem>_tracks.json` | parameters, video metadata, per-track summary, embedded sidecar |

Drop a `<stem>.json` sidecar next to each clip (see `sidecar.example.json`);
`track.py` embeds it in the summary so the future dataset keeps its labels.

Illumination polarity does not matter: MOG2 flags any deviation from the background, so
backlit brightfield (dark swimmers on white, the TOMLOV) and darkfield (bright on black)
run with the same settings. The overlay picks dark or light ink from the first frame.
`synth.py --polarity brightfield` renders the backlit case.

Knobs: `--min-area` is the one you'll turn. `--scale 0.5` for 1080p on the Pi.
`--birth-dist` / `--max-dist` / `--max-missed` / `--min-life` for the tracker. Matching is a
pure-numpy auction (global optimum; `--assign greedy` for v1 behaviour) with an area gate
(`--area-ratio`), blob-size birth suppression (`--fragment-scale`) and gating on the last
measured position as well as the prediction, so reversing swimmers keep their id. Two bodies
sharing one blob (`--merge-ratio`) carry their velocity through it and split by extrapolation.
`python track.py -h` for the rest.

## Simulated ecosystem

`synth.py` draws ellipses. `ecosim.py` draws the cast: procedural sprites per species
(`sprites.py`, drawn from the darkfield references in `references/images.json`) driven by
behaviours (Paramecium avoidance, Didinium capture, Stentor contraction, rotifer release,
Lacrymaria neck, convection drift). Every number lives in `species.py`, in µm and seconds.

```sh
make demo-eco      # ecosim -> track.py -> trackstats.py -> data/eco_fitted.json
make sprites       # sprite sheets + atlas into docs/media/ (docs/sprites.html animates them)
uv run python ecosim.py --out data/eco.mp4 --cast paramecium=8,didinium=2,stentor=1,debris=30
uv run python ecosim.py --dump-params > my.json   # edit, then --params my.json
uv run python trackstats.py data/eco_tracks.csv --emit-params fitted.json
```

`ecosim.py` writes `<stem>_truth.csv` (with species and state), `<stem>_events.csv`
(capture, ingested, contraction, release) and a `<stem>.json` sidecar holding the parameters,
so a tracked clip carries its own model. `trackstats.py` goes the other way: per-track speed,
turn rate and straightness in real units, convection removed by debris consensus, and a
per-species `--params` file when a truth CSV is present. That is the loop that will one day
run on real footage instead of the cheat sheet.

## EcoTaxa

[EcoTaxa](https://ecotaxa.obs-vlfr.fr) is the annotation platform plankton imagers feed, the
PlanktoScope included: one object = images + a row of morphometric features, labelled by people
and by a classifier trained on the features. `ecotaxa.py` makes a tracked clip speak it, so the
v4 species labelling can run on EcoTaxa's UI and classifier instead of a home-grown one.

```sh
uv run python ecotaxa.py export data/eco_tracks.csv --images 5     # -> data/ecotaxa_eco.zip
uv run python ecotaxa.py pull 2748 --out data/ecotaxa --images 20  # the PlanktoScope reference set
make test-network                                                  # live API test, opt in
```

`export` writes an EcoTaxa import bundle: `ecotaxa_<stem>.tsv` (two header rows) plus JPEG crops.
One object per track, up to `--images` frames per object (rank 1 = sharpest), the 33
PlanktoScope morphometrics (`object_area`, `object_major`, `object_circ.`, ...) measured on the
sharpest frame, and motion columns no plankton imager has (`object_speed_mean`,
`object_turn_sigma`, `object_tortuosity`, from `trackstats.py`). Sidecar fields become
`sample_*` / `acq_*` / `process_*`; an ecosim clip exports pre-annotated from its truth CSV
(`object_annotation_status = predicted`, names that resolve on EcoTaxa).

The morphometrics reimplement scikit-image's `regionprops` on OpenCV (perimeter, Euler number
and convex hull are the same algorithms, pixel for pixel; `tests/fixtures/ecotaxa/skimage_blobs.*`
pins that), so no scipy or skimage reaches the Pi.

`pull` reads a public project anonymously: validated objects with taxon names, lineage and
features (`ecotaxa_<id>_objects.csv`), a per-taxon size summary in µm (`ecotaxa_<id>_summary.json`),
optional vignettes. `references/ecotaxa_2748_summary.json` is project 2748, the original
PlanktoScope dataset (Pollina, Lombard, Prakash; Villefranche, January 2020, 20 µm net,
1.19 µm/px, 5806 validated objects): real tintinnids, copepods, nauplii and the not-living
classes (bubble, badfocus, ghost, detritus) a tracker has to reject.

## Pi

`pip install --require-hashes -r requirements.txt` then copy `track.py` (and `trackstats.py` +
`ecotaxa.py` if the Pi should write EcoTaxa bundles).
No scipy. Regenerate the pins with `make requirements`.
