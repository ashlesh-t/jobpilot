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

# 5. Seed the lessons cache if not already present
LESSONS="$JOBPILOT_DIR/cache/apify_lessons.json"
if [ ! -f "$LESSONS" ]; then
  cp "$REPO_DIR/config/apify_lessons_seed.json" "$LESSONS"
  echo "==> Seeded apify_lessons.json with known actor schemas"
else
  echo "==> apify_lessons.json already exists — leaving it untouched"
fi

# 6. Sync slash commands from skills/ to .claude/commands/
mkdir -p "$REPO_DIR/.claude/commands"
for skill_dir in "$REPO_DIR/skills"/*/; do
  skill_name=$(basename "$skill_dir")
  if [ -f "$skill_dir/SKILL.md" ]; then
    cp "$skill_dir/SKILL.md" "$REPO_DIR/.claude/commands/${skill_name}.md"
    echo "    synced: $skill_name"
  fi
done
echo "==> Slash commands synced to .claude/commands/"

# 7. Interactive secrets wizard
echo "==> Launching secrets wizard..."
python3 "$REPO_DIR/scripts/setup_wizard.py"
