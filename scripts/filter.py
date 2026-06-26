"""Layer A hard filter — pure Python, NO LLM.

Applies ONLY location and seen-jobs filters. All other filtering (role relevance, CTC, keyword
match) is handled by Claude in Layer B with real judgment.

Reads /tmp/jobpilot_deduped.json + preferences.json, writes /tmp/jobpilot_filtered.json.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

DEDUPED_IN = "/tmp/jobpilot_deduped.json"
FILTERED_OUT = "/tmp/jobpilot_filtered.json"


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


def seen_job_ids() -> set:
    if not db_path().exists():
        return set()
    try:
        conn = sqlite3.connect(str(db_path()))
        rows = conn.execute(
            "SELECT job_id FROM jobs_seen WHERE status = 'active'"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except sqlite3.Error:
        return set()


def location_ok(job: dict, prefs: dict) -> bool:
    loc = (job.get("location") or "").lower()
    if not loc:
        return True  # unknown location — keep, Claude will judge
    if prefs.get("remote_ok", True) and "remote" in loc:
        return True
    for pref_loc in prefs.get("locations", []):
        pl = pref_loc.lower()
        if pl == "remote" and "remote" in loc:
            return True
        if pl != "remote" and pl in loc:
            return True
    return False


def location_weight(job: dict, prefs: dict) -> float:
    priority = prefs.get("location_priority") or prefs.get("locations", [])
    loc = (job.get("location") or "").lower()
    for i, pref_loc in enumerate(priority):
        pl = pref_loc.lower()
        match = ("remote" in loc) if pl == "remote" else (pl in loc)
        if match:
            if i == 0:
                return 1.0
            elif i == 1:
                return 0.7
            else:
                return 0.4
    return 0.6  # unknown location — neutral weight


def main() -> int:
    jobs = load_json(DEDUPED_IN, [])
    prefs = load_json(jobpilot_dir() / "options" / "preferences.json", {})
    seen = seen_job_ids()

    kept = []
    dropped_location = 0
    dropped_seen = 0

    for job in jobs:
        jid = job.get("job_id", "")
        if jid in seen:
            dropped_seen += 1
            continue
        if not location_ok(job, prefs):
            dropped_location += 1
            continue
        job["location_weight"] = location_weight(job, prefs)
        kept.append(job)

    Path(FILTERED_OUT).write_text(json.dumps(kept, indent=2, ensure_ascii=False))
    print(
        f"Filter: {len(jobs)} in -> {len(kept)} kept | "
        f"dropped: location={dropped_location}, already-seen={dropped_seen} -> {FILTERED_OUT}"
    )
    return len(kept)


if __name__ == "__main__":
    main()
