"""Reset this user's JobPilot history — invoked from Layer B, pure Python, NO LLM.

Usage:
  python3 scripts/jobpilot_clear.py

Deletes this account's cached scoring state (`JobUserScore` rows — lets previously
seen jobs resurface and be rescored), feedback history, and generated reports. Leaves
preferences, profile, resumes, applications, and tailored-resume records untouched —
matches /jobpilot-clear's contract exactly. `company_intel.json` (shared, instance-
wide company research) is deliberately left alone; only this user's own
`learning.json` is removed, since it derives from the feedback rows just deleted.

Requires JOBPILOT_USER_ID in the environment (see scripts/feedback.py).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


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


def clear(user_id: int) -> dict:
    repo_dir = Path(__file__).resolve().parent.parent
    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))
    from core.db import init_db, session_scope
    from core.models import JobUserScore, UserFeedback
    from core.paths import reports_dir, user_dir
    from sqlalchemy import delete

    init_db()
    with session_scope() as s:
        scores_removed = s.execute(
            delete(JobUserScore).where(JobUserScore.user_id == user_id)).rowcount
        feedback_removed = s.execute(
            delete(UserFeedback).where(UserFeedback.user_id == user_id)).rowcount

    reports = reports_dir(user_id)
    reports_removed = 0
    if reports.is_dir():
        for f in reports.iterdir():
            if f.is_file():
                f.unlink()
                reports_removed += 1
            else:
                shutil.rmtree(f, ignore_errors=True)

    learning_path = user_dir(user_id) / "cache" / "learning.json"
    learning_removed = learning_path.is_file()
    if learning_removed:
        learning_path.unlink()

    return {
        "scores_removed": scores_removed,
        "feedback_removed": feedback_removed,
        "reports_removed": reports_removed,
        "learning_reset": learning_removed,
    }


def main() -> None:
    import json

    print(json.dumps(clear(_user_id()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
