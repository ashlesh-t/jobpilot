"""Persist scored jobs — invoked from Layer B, pure Python, NO LLM.

Called by the scoring phase:
  python3 scripts/record_scored.py <scored.json> [--scan-id N]

Writes through `core.repo.jobs.upsert_scored()`, which owns the upsert semantics:
discovery/listing fields land on the shared `Job` row, scoring fields on this user's
own `JobUserScore` row — application status and tailoring history on an existing row
are left alone either way. Requires `JOBPILOT_USER_ID` in the environment — every
pipeline subprocess the orchestrator spawns sets it (see orchestrator/runner.py, and
scripts/jp_secrets.py for the same read-user-from-env pattern).

If `core` isn't importable — a plugin-only checkout without the server dependencies —
it falls back to the v1 SQLite writer so a chat-driven run still records its jobs.
This is what makes cross-run dedupe ("already seen") and the feedback loop work.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jp_paths  # noqa: E402


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def legacy_db_path() -> Path:
    return jobpilot_dir() / "cache" / "jobs.sqlite"


def _user_id() -> int | None:
    raw = os.environ.get("JOBPILOT_USER_ID")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _load(path: str) -> list[dict] | None:
    try:
        data = json.loads(Path(path).read_text())
    except Exception as exc:  # noqa: BLE001
        print(f"[record] cannot read {path}: {exc}", file=sys.stderr)
        return None
    return data if isinstance(data, list) else []


def record_via_core(jobs: list[dict], scan_id: int | None) -> dict | None:
    """Preferred path. Returns counts, or None when core (or a user) isn't available."""
    user_id = _user_id()
    if user_id is None:
        return None
    try:
        from core.db import init_db
        from core.repo import jobs as jobs_repo
    except Exception:
        return None
    init_db()
    return jobs_repo.upsert_scored(user_id, jobs, scan_id=scan_id)


def record_via_sqlite(jobs: list[dict]) -> dict:
    """v1 fallback — the original jobs_seen / score_cache writer."""
    try:
        prefs = json.loads((jobpilot_dir() / "options" / "preferences.json").read_text())
    except Exception:
        prefs = {}
    resume_hash = prefs.get("resume_hash", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = sqlite3.connect(str(legacy_db_path()))
    count = 0
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
            count += 1
        conn.commit()
    finally:
        conn.close()
    return {"inserted": count, "updated": 0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Persist scored jobs")
    ap.add_argument("input", nargs="?", default=jp_paths.artifact("scored"))
    ap.add_argument("--scan-id", type=int, default=None,
                    help="attribute these jobs to a scan (set by the orchestrator)")
    args = ap.parse_args(argv)

    jobs = _load(args.input)
    if jobs is None:
        return 0
    if not jobs:
        print("[record] nothing to record")
        return 0

    scan_id = args.scan_id
    if scan_id is None and os.environ.get("JOBPILOT_SCAN_ID", "").isdigit():
        scan_id = int(os.environ["JOBPILOT_SCAN_ID"])

    result = record_via_core(jobs, scan_id)
    if result is None:
        result = record_via_sqlite(jobs)
        reason = "no JOBPILOT_USER_ID set" if _user_id() is None else "core unavailable"
        print(f"[record] {reason} — wrote {result['inserted']} jobs to jobs.sqlite")
    else:
        print(f"Recorded {result['inserted']} new and {result['updated']} updated jobs")
    return result["inserted"] + result["updated"]


if __name__ == "__main__":
    main()
