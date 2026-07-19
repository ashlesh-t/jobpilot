"""Persist scored jobs into the cache DB — invoked from Layer B, pure Python, NO LLM.

Called by the /job-search skill after scoring (Step B3b):
  python3 scripts/record_scored.py /tmp/jobpilot_scored.json

For every scored job it:
  * upserts jobs_seen (job_id, company, role, location, source, match_score, resume_hash,
    first_seen, last_seen, status='active') — never overwriting a feedback status back to
    'active', and never touching tailored_resume_path (resume_tailor.py owns that column);
  * upserts score_cache (job_id, resume_hash) -> score_json with the fields the learning
    loop needs later: score, matched_skills, missing_skills, archetype, source_board.

This is what makes cross-run dedupe ("already seen") and /job-feedback work: without it,
jobs_seen only ever contained tailored jobs with empty company/role columns.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def db_path() -> Path:
    return jobpilot_dir() / "cache" / "jobs.sqlite"


def main() -> int:
    scored_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/jobpilot_scored.json"
    try:
        jobs = json.loads(Path(scored_path).read_text())
    except Exception as exc:  # noqa: BLE001
        print(f"[record] cannot read {scored_path}: {exc}", file=sys.stderr)
        return 0

    try:
        prefs = json.loads((jobpilot_dir() / "options" / "preferences.json").read_text())
    except Exception:
        prefs = {}
    resume_hash = prefs.get("resume_hash", "")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(str(db_path()))
    seen_n = cache_n = 0
    try:
        for job in jobs:
            jid = job.get("job_id")
            if not jid:
                continue
            try:
                score = round(float(job.get("score") or 0), 1)
            except (TypeError, ValueError):
                score = 0.0
            conn.execute(
                """
                INSERT INTO jobs_seen (job_id, company, role, location, source,
                                       match_score, resume_hash, first_seen, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                ON CONFLICT(job_id) DO UPDATE SET
                  company     = excluded.company,
                  role        = excluded.role,
                  location    = excluded.location,
                  source      = excluded.source,
                  match_score = excluded.match_score,
                  resume_hash = excluded.resume_hash,
                  last_seen   = excluded.last_seen
                """,
                (jid, job.get("company", ""), job.get("role", ""),
                 job.get("location", ""), job.get("source_board", ""),
                 score, resume_hash, now, now),
            )
            seen_n += 1

            score_json = json.dumps({
                "score": score,
                "keyword_score": job.get("keyword_score"),
                "semantic_score": job.get("semantic_score"),
                "matched_skills": job.get("matched_skills") or [],
                "missing_skills": job.get("missing_skills") or [],
                "archetype": job.get("archetype", ""),
                "source_board": job.get("source_board", ""),
            }, ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO score_cache (job_id, resume_hash, score_json, computed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id, resume_hash) DO UPDATE SET
                  score_json = excluded.score_json,
                  computed_at = excluded.computed_at
                """,
                (jid, resume_hash, score_json, now),
            )
            cache_n += 1
        conn.commit()
    finally:
        conn.close()

    print(f"Recorded {seen_n} jobs into jobs_seen, {cache_n} into score_cache")
    return seen_n


if __name__ == "__main__":
    main()
