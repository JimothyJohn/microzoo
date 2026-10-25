#!/usr/bin/env bash
# Synthetic swimmers -> track.py -> data/demo_tracks.mp4, _tracks.csv, _follow_<id>.mp4
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
uv run python synth.py --out data/demo.mp4 --n 6 --frames 300 --fps 30 --size 640x480 --seed 1
uv run python track.py data/demo.mp4 --min-area 20
# Same tank, backlit: dark swimmers on a bright field, as the TOMLOV sees it.
uv run python synth.py --out data/demo_bf.mp4 --n 6 --frames 300 --fps 30 --size 640x480 --seed 1 --polarity brightfield
uv run python track.py data/demo_bf.mp4 --min-area 20
ls -la data/demo*
