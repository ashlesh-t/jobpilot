#!/usr/bin/env bash
# JobPilot one-time setup (Linux/macOS convenience shim).
# The real, cross-platform logic lives in scripts/jobpilot_setup.py so Windows works too.
# Idempotent — safe to re-run.  On Windows, run: python scripts\jobpilot_setup.py
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "!!  Python 3.11+ not found. Install it, then run: python scripts/jobpilot_setup.py" >&2
  exit 1
fi

exec "$PY" "$REPO_DIR/scripts/jobpilot_setup.py" "$@"
