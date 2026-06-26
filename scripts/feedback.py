"""Thin CLI wrapper to record user feedback on jobs.

Usage:
  python3 scripts/feedback.py <job_id> <status> [--notes "text"]

Status values: applied, rejected, interview, offer, ghosted
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VALID_STATUSES = {"applied", "rejected", "interview", "offer", "ghosted"}


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def db_path() -> Path:
    return jobpilot_dir() / "cache" / "jobs.sqlite"


def record_feedback(job_id: str, status: str, notes: str = "") -> None:
    import sqlite3

    status = status.lower().strip()
    if status not in VALID_STATUSES:
        print(f"Error: status must be one of {sorted(VALID_STATUSES)}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(str(db_path()))
    try:
        conn.execute(
            """
            INSERT INTO user_feedback (job_id, status, notes, feedback_date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              status = excluded.status,
              notes = excluded.notes,
              feedback_date = excluded.feedback_date
            """,
            (job_id, status, notes, now),
        )
        conn.execute(
            "UPDATE jobs_seen SET status = ? WHERE job_id = ?",
            (status, job_id),
        )
        conn.commit()
        print(f"Recorded: {job_id} → {status}" + (f" ({notes})" if notes else ""))
    finally:
        conn.close()


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: python3 feedback.py <job_id> <status> [--notes 'text']", file=sys.stderr)
        sys.exit(1)

    job_id = args[0]
    status = args[1]
    notes = ""

    if "--notes" in args:
        idx = args.index("--notes")
        if idx + 1 < len(args):
            notes = args[idx + 1]

    record_feedback(job_id, status, notes)


if __name__ == "__main__":
    main()
