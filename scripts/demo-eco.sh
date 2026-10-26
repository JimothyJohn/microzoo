#!/usr/bin/env bash
# The loop on synthetic data: species.py numbers -> ecosim clip -> track.py -> trackstats.py
# -> data/eco_fitted.json, a --params file ecosim.py can consume again.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
uv run python ecosim.py --out data/eco.mp4 --frames 450 --fps 30 --size 640x480 --um-per-px 3 --seed 1
uv run python track.py data/eco.mp4 --min-area 20
uv run python trackstats.py data/eco_tracks.csv --json data/eco_stats.json --emit-params data/eco_fitted.json
# Same cast, backlit, as the TOMLOV sees it.
uv run python ecosim.py --out data/eco_bf.mp4 --frames 200 --fps 30 --size 640x480 --um-per-px 3 --seed 1 --polarity brightfield
uv run python track.py data/eco_bf.mp4 --min-area 20
ls -la data/eco*
