#!/usr/bin/env bash
# JobPilot one-time setup. Idempotent — safe to re-run.
set -euo pipefail

JOBPILOT_DIR="${JOBPILOT_DIR:-$HOME/.claude/job-hunt-ai}"
JOBPILOT_DIR="${JOBPILOT_DIR/#\~/$HOME}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> JobPilot setup starting"
echo "    Repo:      $REPO_DIR"
echo "    Data dir:  $JOBPILOT_DIR"

# 1. Create data directory tree
mkdir -p "$JOBPILOT_DIR/options" \
         "$JOBPILOT_DIR/resumes/tailored" \
         "$JOBPILOT_DIR/cache" \
         "$JOBPILOT_DIR/reports"
echo "==> Created data directories"

# 2. Copy default preferences if not present
PREFS="$JOBPILOT_DIR/options/preferences.json"
if [ ! -f "$PREFS" ]; then
  cp "$REPO_DIR/config/preferences.example.json" "$PREFS"
  echo "==> Installed default preferences.json"
else
  echo "==> preferences.json already exists — leaving it untouched"
fi

# 3. Initialise the SQLite cache from schema
DB="$JOBPILOT_DIR/cache/jobs.sqlite"
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" < "$REPO_DIR/schema/init.sql"
  echo "==> Initialised SQLite cache at $DB"
else
  echo "!!  sqlite3 not found — install it, then run: sqlite3 \"$DB\" < schema/init.sql"
fi

# 4. Install Python dependencies
if command -v pip3 >/dev/null 2>&1; then
  pip3 install -r "$REPO_DIR/requirements.txt"
  echo "==> Installed Python dependencies"
else
  echo "!!  pip3 not found — install Python 3.11+ then: pip3 install -r requirements.txt"
fi

# 5. Interactive secrets wizard
echo "==> Launching secrets wizard..."
python3 "$REPO_DIR/scripts/setup_wizard.py"
