"""Layer A dedupe — pure Python, NO LLM.

Removes jobs already seen (jobs_seen status='active'), dedupes within the batch on a
(company|role|location) hash, and clears the score cache if the resume hash changed.
Reads /tmp/jobpilot_raw.json, writes /tmp/jobpilot_deduped.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

RAW_IN = "/tmp/jobpilot_raw.json"
DEDUPED_OUT = "/tmp/jobpilot_deduped.json"


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def db_path() -> Path:
    return jobpilot_dir() / "cache" / "jobs.sqlite"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def batch_key(job: dict) -> str:
    raw = (
        str(job.get("company", "")).lower()
        + str(job.get("role", "")).lower()
        + str(job.get("location", "")).lower()
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def seen_job_ids(conn) -> set:
    try:
        rows = conn.execute(
            "SELECT job_id FROM jobs_seen WHERE status = 'active'"
        ).fetchall()
        return {r[0] for r in rows}
    except sqlite3.Error:
        return set()


def stored_resume_hash(conn) -> str | None:
    try:
        row = conn.execute(
            "SELECT resume_hash FROM jobs_seen WHERE resume_hash IS NOT NULL "
            "ORDER BY last_seen DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def main() -> int:
    raw = load_json(RAW_IN, [])
    before = len(raw)
    prefs = load_json(jobpilot_dir() / "options" / "preferences.json", {})
    current_hash = prefs.get("resume_hash", "")

    conn = None
    seen = set()
    if db_path().exists():
        conn = sqlite3.connect(str(db_path()))
        seen = seen_job_ids(conn)

        # If the resume changed, the cached scores are stale -> clear score_cache only.
        prev_hash = stored_resume_hash(conn)
        if current_hash and prev_hash and current_hash != prev_hash:
            conn.execute("DELETE FROM score_cache")
            conn.commit()
            print("[dedupe] resume hash changed -> cleared score_cache", file=sys.stderr)

    deduped = []
    batch_seen_keys = set()
    removed_seen = 0
    removed_batch = 0
    for job in raw:
        jid = job.get("job_id")
        if jid in seen:
            removed_seen += 1
            continue
        key = batch_key(job)
        if key in batch_seen_keys:
            removed_batch += 1
            continue
        batch_seen_keys.add(key)
        deduped.append(job)

    if conn:
        conn.close()

    Path(DEDUPED_OUT).write_text(json.dumps(deduped, indent=2, ensure_ascii=False))
    after = len(deduped)
    print(
        f"Dedupe: {before} raw -> {after} kept "
        f"({removed_seen} already-seen, {removed_batch} in-batch duplicates) -> {DEDUPED_OUT}"
    )
    return after


if __name__ == "__main__":
    main()
