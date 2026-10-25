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

## Pi

`pip install --require-hashes -r requirements.txt` then copy `track.py`.
No scipy. Regenerate the pins with `make requirements`.
