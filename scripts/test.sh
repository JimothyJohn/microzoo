#!/usr/bin/env bash
# Usage: scripts/test.sh [unit|integration|all]
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-all}" in
  unit)        uv run pytest -m "not integration" ;;
  integration) uv run pytest -m integration ;;
  all)         uv run pytest ;;
  *) echo "unknown suite: $1" >&2; exit 2 ;;
esac
