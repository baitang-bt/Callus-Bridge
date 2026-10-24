#!/usr/bin/env bash
# Start the non-GUI openclaw wejam.v1 bridge (default 127.0.0.1:7702).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "缺少 .venv，先: python3 -m venv .venv && .venv/bin/pip install -e '.[openclaw]'" >&2
  exit 1
fi
export WEJAM_PORT="${WEJAM_PORT:-7702}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m openclaw
