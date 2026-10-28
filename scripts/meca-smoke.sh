#!/usr/bin/env bash
# First contact with the real Meca500 through stage.py: read the pose, then a
# 100 µm square in X and Y at 1 mm/s and back. Never moves Z.
#
# Needs: the robot on the LAN at MECA_HOST (default 192.168.0.100), activated
# and homed, holding the slide (or nothing) clear of the objective, and no
# other client on its control port (one connection at a time). Cell clear.
#
# Proves the wiring and the command strings, not the accuracy: GetPose reports
# the robot's target pose, so "got" matching "asked" means the moves were
# accepted. Accuracy is a camera job (track a particle while it moves).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${MECA_HOST:-192.168.0.100}"

if ! nc -z -G 3 "$HOST" 10000 2>/dev/null; then
  echo "meca-smoke: nothing listening on $HOST:10000 (set MECA_HOST?)" >&2
  exit 1
fi
uv run python stage.py --host "$HOST" pose
uv run python stage.py --host "$HOST" smoke --speed 1000
echo "meca-smoke: ok"
