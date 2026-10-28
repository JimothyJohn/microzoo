#!/usr/bin/env bash
# Cut the real-footage regression clips for `pytest --real-clips=data/real`.
#
# Needs: ffmpeg + ffprobe, and the two YouTube downloads in SRC_DIR (yt-dlp names,
# matched by video id): KvIp8C5WPvs (rotifer in debris, 8 s) and _IicIlcotgI
# (53-min pond-water compilation). Third-party footage: the clips land in the
# gitignored data/real/ and are never committed.
#
# Usage: scripts/real-clips.sh SRC_DIR [OUT_DIR]   (OUT_DIR defaults to data/real)
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
  input=$(find_src "$id")
  if [[ -f "$dst" ]] && { [[ $n -eq 0 ]] || [[ $(frames "$dst") -eq $n ]]; }; then
    echo "real-clips: $dst ok"
    return
  fi
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

[[ $(frames "$out/kvip.mp4") -eq 246 ]] || { echo "real-clips: kvip is not 246 frames" >&2; exit 1; }
echo "real-clips: done -> uv run pytest --real-clips=$out -m real"
