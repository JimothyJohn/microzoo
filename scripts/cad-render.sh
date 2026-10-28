#!/usr/bin/env bash
# Render every printable part of a cad/*.scad file to STL, plus the echo report.
# Needs: OpenSCAD on PATH, $OPENSCAD, or an OpenSCAD*.app in /Applications or a mounted
# DMG (Homebrew's cask is disabled; get it from openscad.org).
# Idempotent: overwrites data/cad/<file>_<part>.stl.
# Usage: scripts/cad-render.sh [cad/dish_ring.scad] [part ...]
#        scripts/cad-render.sh cad/dish_ring.scad meca_adapter   # once MECA_BCD is set
set -euo pipefail
cd "$(dirname "$0")/.."

src="${1:-cad/dish_ring.scad}"
shift || true
parts=("$@")
if [ ${#parts[@]} -eq 0 ]; then
  # meca_adapter is left out until MECA_BCD is measured: it asserts on purpose
  parts=(base seat stop diffuser)
fi

scad="${OPENSCAD:-$(command -v openscad || true)}"
if [ -z "$scad" ]; then
  # the macOS app, including versioned names (OpenSCAD-2021.01.app) and a mounted DMG
  for app in /Applications/OpenSCAD*.app ~/Applications/OpenSCAD*.app /Volumes/OpenSCAD*/OpenSCAD*.app; do
    if [ -x "$app/Contents/MacOS/OpenSCAD" ]; then
      scad="$app/Contents/MacOS/OpenSCAD"
      break
    fi
  done
fi
if [ -z "$scad" ]; then
  echo "cad-render: OpenSCAD not found (install from https://openscad.org)" >&2
  exit 2
fi

out=data/cad
mkdir -p "$out"
stem="$(basename "$src" .scad)"
fail=0
for p in "${parts[@]}"; do
  stl="$out/${stem}_${p}.stl"
  if "$scad" -o "$stl" -D "part=\"$p\"" "$src" 2>"$out/${stem}_${p}.log"; then
    echo "ok   $stl"
  else
    echo "FAIL $p (see $out/${stem}_${p}.log)" >&2
    grep -E "ERROR|Assertion" "$out/${stem}_${p}.log" >&2 || true
    fail=1
  fi
done
grep -h "ECHO" "$out/${stem}_${parts[0]}.log" || true
# a cut-away preview (ghosts included) to check the fit by eye, if the file has one
if grep -q '"section"' "$src"; then
  png="$out/${stem}_section.png"
  if "$scad" -o "$png" -D 'part="section"' --imgsize=1600,900 --projection=o \
      --camera=0,0,10,90,0,0,260 --colorscheme=Tomorrow "$src" 2>/dev/null; then
    echo "ok   $png"
  fi
fi
exit "$fail"
