#!/usr/bin/env bash
# The Meca500 stage in simulation: the speed/magnification table, then the
# camera's view while the robot follows a Paramecium at 10x, scans tiles at 4x,
# and sweeps focus through the chamber.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
uv run python stagesim.py table | tee data/meca_table.md
uv run python stagesim.py run --out data/meca_follow.mp4 --mode follow --objective 10x --frames 300
uv run python stagesim.py run --out data/meca_scan.mp4 --mode scan --objective 4x --tiles 3x2 --frames 300
uv run python stagesim.py run --out data/meca_zsweep.mp4 --mode zsweep --objective 10x --frames 180
ls -la data/meca*
