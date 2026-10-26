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
`--birth-dist` / `--max-dist` / `--max-missed` / `--min-life` for the tracker.
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

## Pi

`pip install --require-hashes -r requirements.txt` then copy `track.py`.
No scipy. Regenerate the pins with `make requirements`.
