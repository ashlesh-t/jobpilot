"""List recent jobs worth asking about — invoked from Layer B, pure Python, NO LLM.

Usage:
  python3 scripts/feedback_candidates.py [--limit N]

Prints a JSON array of this user's jobs that have an application, a tailored resume,
or an existing feedback row — the same "worth following up on" set /job-feedback's v1
incarnation queried from jobs_seen/score_cache, now read from the v2 database via
core.repo. Requires JOBPILOT_USER_ID in the environment (see scripts/feedback.py).
"""
from __future__ import annotations

import argparse
import json
import os
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


def candidates(user_id: int, limit: int) -> list[dict]:
    repo_dir = Path(__file__).resolve().parent.parent
    if str(repo_dir) not in sys.path:
        sys.path.insert(0, str(repo_dir))
    from core.db import init_db, session_scope
    from core.models import Application, Job, JobUserScore, TailoredResume, UserFeedback
    from sqlalchemy import select

    init_db()
    with session_scope() as s:
        job_ids: set[str] = set()
        job_ids |= set(s.scalars(select(Application.job_id).where(Application.user_id == user_id)))
        job_ids |= set(s.scalars(select(TailoredResume.job_id).where(TailoredResume.user_id == user_id)))
        job_ids |= set(s.scalars(select(UserFeedback.job_id).where(UserFeedback.user_id == user_id)))
        if not job_ids:
            return []

        rows = s.execute(
            select(Job, JobUserScore)
            .outerjoin(JobUserScore, (JobUserScore.job_id == Job.job_id) & (JobUserScore.user_id == user_id))
            .where(Job.job_id.in_(job_ids))
            .order_by(Job.last_seen.desc())
            .limit(limit)
        ).all()
        feedback = {
            f.job_id: f.status
            for f in s.scalars(select(UserFeedback).where(UserFeedback.user_id == user_id,
                                                           UserFeedback.job_id.in_(job_ids)))
        }
        return [
            {
                "job_id": job.job_id,
                "company": job.company,
                "role": job.role,
                "location": job.location,
                "score": round(score.score, 1) if score else 0.0,
                "feedback_status": feedback.get(job.job_id, "pending"),
                # For /job-feedback Step 3b's learning-weight update — the signals a
                # recorded outcome should nudge, without a second script invocation.
                "matched_skills": (score.matched_skills if score else []) or [],
                "archetype": score.archetype if score else "",
                "source_board": job.source_board,
            }
            for job, score in rows
        ]


def main() -> None:
    ap = argparse.ArgumentParser(description="List recent applied/tailored jobs for /job-feedback")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    print(json.dumps(candidates(_user_id(), args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
