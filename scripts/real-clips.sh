#!/usr/bin/env bash
# Cut the real-footage regression clips for `pytest --real-clips=data/real`.
#
# Needs: ffmpeg + ffprobe, and the two YouTube downloads in SRC_DIR (yt-dlp names,
# matched by video id): KvIp8C5WPvs (rotifer in debris, 8 s) and _IicIlcotgI
# (53-min pond-water compilation). Third-party footage: the clips land in the
# gitignored data/real/ and are never committed.
#
# Plus one clip of our own (TOMLOV, 2026-11-07), looked up by name in OWN_DIR.
#
# Usage: [OWN_DIR=dir] scripts/real-clips.sh SRC_DIR [OUT_DIR]
#        (OUT_DIR defaults to data/real, OWN_DIR to SRC_DIR)
# Idempotent: existing clips with the right frame count are kept.
set -euo pipefail
cd "$(dirname "$0")/.."

src=${1:?usage: scripts/real-clips.sh SRC_DIR [OUT_DIR]}
out=${2:-data/real}
mkdir -p "$out"

find_src() {
  local hit
  hit=$(find "$src" -maxdepth 1 -name "*\[$1\]*" | head -n 1)
  [[ -n "$hit" ]] || { echo "real-clips: no file with id $1 in $src" >&2; exit 1; }
  printf '%s\n' "$hit"
}

frames() {
  ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=nb_read_frames -of csv=p=0 "$1"
}

# name, source id, first frame, frame count (source is 30 fps; 0 0 = whole clip)
cut() {
  local name=$1 id=$2 first=$3 n=$4 dst="$out/$1.mp4" input
  if [[ -f "$dst" ]] && { [[ $n -eq 0 ]] || [[ $(frames "$dst") -eq $n ]]; }; then
    echo "real-clips: $dst ok"
    return
  fi
  input=$(find_src "$id")
  if [[ $n -eq 0 ]]; then
    ffmpeg -v error -y -i "$input" -an -c:v libx264 -crf 18 -pix_fmt yuv420p "$dst"
  else
    ffmpeg -v error -y -ss "$(awk "BEGIN{print $first/30}")" -i "$input" -frames:v "$n" \
      -an -c:v libx264 -crf 18 -pix_fmt yuv420p "$dst"
  fi
  echo "real-clips: wrote $dst ($(frames "$dst") frames)"
}

cut kvip KvIp8C5WPvs 0 0          # rotifer pausing in debris, brightfield
cut d3 _IicIlcotgI 32615 416      # darkfield, static debris, nothing swims
cut b3 _IicIlcotgI 41615 779      # empty brightfield: the negative control
cut b4 _IicIlcotgI 84492 848      # brightfield debris mat, a parked animal

# Own footage: the TOMLOV TM3K-3D, handheld, 60 fps. Found by file name in
# $OWN_DIR (default SRC_DIR). Its sidecar is written next to the clip so
# track.py carries it into <stem>_tracks.json.
own=${OWN_DIR:-$src}
tomlov_src="$own/2026-11-07 15-32-52.mp4"
[[ -f "$tomlov_src" ]] || { echo "real-clips: missing $tomlov_src (set OWN_DIR)" >&2; exit 1; }
tomlov="$out/tomlov_swim.mp4"
if [[ -f "$tomlov" ]] && [[ $(frames "$tomlov") -eq 1320 ]]; then
  echo "real-clips: $tomlov ok"
else
  # frame 11700 = 195.0 s; the last 22 s of the clip, after the scope stopped moving
  ffmpeg -v error -y -ss 195 -i "$tomlov_src" -frames:v 1320 \
    -an -c:v libx264 -crf 16 -pix_fmt yuv420p "$tomlov"
  echo "real-clips: wrote $tomlov ($(frames "$tomlov") frames)"
fi
cat > "$out/tomlov_swim.json" <<'EOF'
{
  "date": "2026-11-07",
  "source": "2026-11-07 15-32-52.mp4, 195.0-217.0 s",
  "source_jar": "not recorded",
  "chamber": "open dish, depth not recorded",
  "objective": "TOMLOV TM3K-3D, zoom not recorded (no scale bar)",
  "illumination": "not recorded; lamp glare off the dish wall in frame",
  "exposure": "auto",
  "fps": 60,
  "notes": "one small oval swimmer enters top right at ~12.7 s and glides ~9 s down a curved path at ~85 px/s; the bright teardrop and ellipse are static glare"
}
EOF

[[ $(frames "$out/kvip.mp4") -eq 246 ]] || { echo "real-clips: kvip is not 246 frames" >&2; exit 1; }
[[ $(frames "$tomlov") -eq 1320 ]] || { echo "real-clips: tomlov_swim is not 1320 frames" >&2; exit 1; }
echo "real-clips: done -> uv run pytest --real-clips=$out -m real"
