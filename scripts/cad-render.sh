#!/usr/bin/env bash
# Render every printable part of a cad/*.scad file to STL, plus the echo report.
# Needs: OpenSCAD on PATH or at /Applications/OpenSCAD.app (Homebrew's cask is disabled;
# install from openscad.org). Idempotent: overwrites data/cad/<file>_<part>.stl.
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

scad="$(command -v openscad || true)"
if [ -z "$scad" ] && [ -x /Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD ]; then
  scad=/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD
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
exit "$fail"
