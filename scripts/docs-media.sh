#!/usr/bin/env bash
# Regenerate docs/media for docs/sprites.html: sprite sheets + atlas, three ecosim clips,
# one tracked clip (h264, crf 30, ~1 MB each), and a copy of the reference catalogue.
# The previews are rendered as the owned TOMLOV TM3K-3D would see the chamber: ~2.9 mm
# across at 640 px (4.5 µm/px) with its 10-20 µm resolution floor (--blur-um 15), top light
# on a black stage for darkfield, backlit for brightfield. HUNT is its zoomed view.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v ffmpeg >/dev/null || { echo "ffmpeg not found" >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p docs/media
uv run python sprites.py --sheet docs/media/sprites.png --atlas docs/media/sprites.json --frames 12 --cell 128
TOMLOV="--um-per-px 4.5 --blur-um 15 --noise 5"
uv run python ecosim.py --out "$tmp/eco.mp4" --frames 450 --fps 30 --size 640x480 $TOMLOV --seed 1 --polarity darkfield
uv run python ecosim.py --out "$tmp/eco_bf.mp4" --frames 450 --fps 30 --size 640x480 $TOMLOV --seed 1 --polarity brightfield
uv run python ecosim.py --out "$tmp/hunt.mp4" --frames 360 --fps 30 --size 640x480 --um-per-px 2.2 --blur-um 15 --noise 5 --seed 21 --cast paramecium=5,didinium=1,debris=15 --polarity brightfield
uv run python track.py "$tmp/eco.mp4" --min-area 20
for stem in eco eco_bf hunt eco_tracks; do
  ffmpeg -v error -y -i "$tmp/$stem.mp4" -c:v libx264 -preset slow -crf 30 -pix_fmt yuv420p -movflags +faststart "docs/media/$stem.mp4"
done
cp references/images.json docs/media/references.json
ls -la docs/media
