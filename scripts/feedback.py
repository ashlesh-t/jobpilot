"""Thin CLI wrapper to record user feedback on jobs.

Usage:
  python3 scripts/feedback.py <job_id> <status> [--notes "text"]

Status values: applied, rejected, interview, offer, ghosted

Writes to the v2 database (core.models.UserFeedback, composite PK (user_id, job_id)).
Requires JOBPILOT_USER_ID in the environment — every pipeline subprocess the
orchestrator spawns sets it (see orchestrator/runner.py, and scripts/jp_secrets.py for
the same read-user-from-env pattern).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VALID_STATUSES = {"applied", "rejected", "interview", "offer", "ghosted"}


def _user_id() -> int:
    raw = os.environ.get("JOBPILOT_USER_ID")
    if not raw:
        print("Error: JOBPILOT_USER_ID is not set in the environment", file=sys.stderr)
        sys.exit(1)
    try:
        return int(raw)
    except ValueError:
        print(f"Error: invalid JOBPILOT_USER_ID {raw!r}", file=sys.stderr)
        sys.exit(1)


def _core():
    """Lazily import the core DB layer — only paid for when this script actually runs."""
    repo_dir = Path(__file__).resolve().parent.parent
    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))
    from core.db import session_scope
    from core.models import UserFeedback

    return session_scope, UserFeedback


def record_feedback(job_id: str, status: str, notes: str = "") -> None:
    status = status.lower().strip()
    if status not in VALID_STATUSES:
        print(f"Error: status must be one of {sorted(VALID_STATUSES)}", file=sys.stderr)
        sys.exit(1)

    user_id = _user_id()
    session_scope, UserFeedback = _core()
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        row = s.get(UserFeedback, (user_id, job_id))
        if row is None:
            row = UserFeedback(user_id=user_id, job_id=job_id)
            s.add(row)
        row.status = status
        row.notes = notes
        row.feedback_date = now
    print(f"Recorded: {job_id} → {status}" + (f" ({notes})" if notes else ""))


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
