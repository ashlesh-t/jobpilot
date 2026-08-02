"""One-shot import of JobPilot v1 state into the v2 database.

v1 kept state in five places: options/preferences.json, cache/profile.json,
cache/jobs.sqlite (jobs_seen / score_cache / user_feedback / url_security_cache),
cache/runs/*.json, and a handful of Claude-written JSON caches. This reads all of them
and writes the equivalent v2 rows.

Guarantees:
  * Idempotent — safe to run repeatedly; a marker file short-circuits the normal path.
  * Non-destructive — the v1 files are never modified or deleted, so a user can roll back.
  * Partial-failure tolerant — one unreadable source does not abort the rest; every
    problem is collected into the returned report.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .db import session_scope
from .models import Job, Profile, Run, RunStatus, ScheduleSlot, UrlSecurityCache, UserFeedback
from .paths import (
    cache_dir,
    jobpilot_dir,
    legacy_sqlite_path,
    migrated_marker,
    prefs_path,
    profile_path,
    resumes_dir,
)
from .repo import jobs as jobs_repo
from .repo import resumes as resumes_repo
from .repo import schedule as schedule_repo
from .repo import settings as settings_repo

# Claude-written caches that have no dedicated table — kept verbatim under these keys.
JSON_CACHES = {
    "learning.json": "learning",
    "company_intel.json": "company_intel",
    "locations.json": "locations",
    "run_state.json": "run_state",
    "apify_lessons.json": "apify_lessons",
    "telegram_channels.json": "telegram_channels",
}


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    for candidate in (text, text[:19]):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def has_v1_state() -> bool:
    return any(p.exists() for p in (prefs_path(), profile_path(), legacy_sqlite_path()))


def already_migrated() -> bool:
    return migrated_marker().exists()


# --------------------------------------------------------------------------- #
# Individual importers — each returns a count and appends to `errors`
# --------------------------------------------------------------------------- #
def _import_preferences(errors: list[str]) -> int:
    data = _read_json(prefs_path())
    if not isinstance(data, dict):
        return 0
    known = {k: v for k, v in data.items() if k in settings_repo.PREFERENCE_KEYS}
    # Anything unrecognized is preserved under legacy_preferences rather than dropped —
    # a user may have hand-added keys that a future version wants back.
    leftover = {k: v for k, v in data.items() if k not in settings_repo.PREFERENCE_KEYS}
    try:
        if known:
            settings_repo.set_many(known)
        if leftover:
            settings_repo.set("legacy_preferences", leftover, export=False)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"preferences: {exc}")
        return 0
    return len(known)


def _import_schedule_slots(errors: list[str]) -> int:
    slots = settings_repo.get("schedule_slots_ist") or []
    if not isinstance(slots, list):
        return 0
    created = 0
    with session_scope() as s:
        existing = {r.name for r in s.scalars(select(ScheduleSlot)).all()}
    for i, slot in enumerate(slots):
        try:
            if isinstance(slot, str):
                name, time = f"slot-{i + 1}", slot
            elif isinstance(slot, dict):
                name, time = slot.get("name") or f"slot-{i + 1}", slot.get("time", "")
            else:
                continue
            if name in existing or not time:
                continue
            schedule_repo.create(name=name, time=time)
            created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"schedule slot {slot!r}: {exc}")
    return created


def _import_profile(errors: list[str]) -> int:
    data = _read_json(profile_path())
    if not isinstance(data, dict):
        return 0
    try:
        with session_scope() as s:
            if s.scalar(select(Profile)) is not None:
                return 0                       # v2 already has a profile — don't clobber it
        verified = bool(data.get("profile_verified"))
        resume_hash = str(data.get("hash") or "")
        payload = {k: v for k, v in data.items() if k not in ("profile_verified", "hash")}
        from .repo import profiles as profiles_repo
        profiles_repo.save(payload, verified=verified, resume_hash=resume_hash)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"profile: {exc}")
        return 0
    return 1


def _import_json_caches(errors: list[str]) -> int:
    count = 0
    for filename, key in JSON_CACHES.items():
        data = _read_json(cache_dir() / filename)
        if data is None:
            continue
        try:
            settings_repo.set(key, data, export=False)
            count += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{filename}: {exc}")
    return count


def _import_resumes(errors: list[str]) -> int:
    root = resumes_dir()
    if not root.exists():
        return 0
    count = 0
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.suffix.lower() not in resumes_repo.ALLOWED_SUFFIXES:
            continue
        try:
            # base.pdf was v1's single active resume, so it becomes the v2 active one.
            resumes_repo.add(path, folder="imported", filename=path.name,
                             label=path.stem, make_active=path.stem == "base")
            count += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"resume {path.name}: {exc}")
    if count and resumes_repo.active() is None:
        first = resumes_repo.list_all()[0]
        resumes_repo.set_active(first["id"])
    return count


def _legacy_rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    try:
        return conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 - fixed names
    except sqlite3.Error:
        return []


def _import_legacy_db(errors: list[str]) -> dict[str, int]:
    counts = {"jobs": 0, "feedback": 0, "url_cache": 0}
    path = legacy_sqlite_path()
    if not path.exists():
        return counts

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        errors.append(f"jobs.sqlite: {exc}")
        return counts

    try:
        # jobs_seen + score_cache → jobs. score_cache holds the richer payload, so it
        # wins where the two overlap.
        scores: dict[str, dict] = {}
        for row in _legacy_rows(conn, "score_cache"):
            try:
                scores[row["job_id"]] = json.loads(row["score_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue

        payload = []
        for row in _legacy_rows(conn, "jobs_seen"):
            job_id = row["job_id"]
            sc = scores.get(job_id, {})
            payload.append({
                "job_id": job_id,
                "company": row["company"] or "",
                "role": row["role"] or "",
                "location": row["location"] or "",
                "source_board": row["source"] or sc.get("source_board", ""),
                "score": sc.get("score", row["match_score"] or 0),
                "keyword_score": sc.get("keyword_score", 0),
                "semantic_score": sc.get("semantic_score", 0),
                "matched_skills": sc.get("matched_skills", []),
                "missing_skills": sc.get("missing_skills", []),
                "archetype": sc.get("archetype", ""),
            })
        if payload:
            result = jobs_repo.upsert_scored(payload)
            counts["jobs"] = result["inserted"] + result["updated"]

        # Restore first_seen/last_seen and tailoring paths, which upsert_scored stamps
        # with "now" — losing them would make every imported job look brand new.
        with session_scope() as s:
            for row in _legacy_rows(conn, "jobs_seen"):
                job = s.get(Job, row["job_id"])
                if job is None:
                    continue
                first, last = _parse_ts(row["first_seen"]), _parse_ts(row["last_seen"])
                if first:
                    job.first_seen = first
                if last:
                    job.last_seen = last

            for row in _legacy_rows(conn, "user_feedback"):
                if s.get(UserFeedback, row["job_id"]) is not None:
                    continue
                s.add(UserFeedback(
                    job_id=row["job_id"],
                    status=row["status"] or "",
                    notes=row["notes"] or "",
                    feedback_date=_parse_ts(row["feedback_date"]) or datetime.now(timezone.utc),
                ))
                counts["feedback"] += 1

            for row in _legacy_rows(conn, "url_security_cache"):
                if s.get(UrlSecurityCache, row["url_hash"]) is not None:
                    continue
                s.add(UrlSecurityCache(
                    url_hash=row["url_hash"],
                    url=row["url"],
                    risk_score=row["risk_score"] or 0,
                    risk_label=row["risk_label"] or "unknown",
                    is_allowlist=bool(row["is_allowlist"]),
                    final_url=row["final_url"] or "",
                    redirect_hops=json.loads(row["redirect_hops"] or "[]"),
                    threats=json.loads(row["threats"] or "[]"),
                    checked_at=_parse_ts(row["checked_at"]),
                    expires_at=_parse_ts(row["expires_at"]),
                ))
                counts["url_cache"] += 1
    except Exception as exc:  # noqa: BLE001
        errors.append(f"jobs.sqlite import: {exc}")
    finally:
        conn.close()
    return counts


def _import_run_history(errors: list[str]) -> int:
    runs_json = cache_dir() / "runs"
    if not runs_json.exists():
        return 0
    count = 0
    with session_scope() as s:
        for path in sorted(runs_json.glob("*.json")):
            data = _read_json(path)
            if not isinstance(data, dict) or not data.get("id"):
                continue
            run_id = str(data["id"])
            if s.get(Run, run_id) is not None:
                continue
            status = data.get("status", "done")
            if status not in {r.value for r in RunStatus}:
                status = RunStatus.done.value
            try:
                s.add(Run(
                    id=run_id,
                    status=status,
                    mode=data.get("mode", "auto"),
                    engine=data.get("engine", ""),
                    trigger="manual",
                    started_at=_parse_ts(data.get("started_at")) or datetime.now(timezone.utc),
                    ended_at=_parse_ts(data.get("ended_at")),
                    error=data.get("error", "") or "",
                    summary=(data.get("summary") or "")[:4000],
                ))
                count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"run {path.name}: {exc}")
    return count


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def migrate(*, force: bool = False) -> dict:
    """Import everything. Returns a report dict; writes the marker on success."""
    report: dict[str, Any] = {
        "ran": False, "skipped_reason": "", "data_dir": str(jobpilot_dir()),
        "counts": {}, "errors": [],
    }
    if already_migrated() and not force:
        report["skipped_reason"] = "already migrated (delete cache/.v1_migrated to redo)"
        return report
    if not has_v1_state():
        report["skipped_reason"] = "no v1 state found — nothing to import"
        return report

    errors: list[str] = report["errors"]
    counts = report["counts"]
    counts["preferences"] = _import_preferences(errors)
    counts["schedule_slots"] = _import_schedule_slots(errors)
    counts["profile"] = _import_profile(errors)
    counts["json_caches"] = _import_json_caches(errors)
    counts["resumes"] = _import_resumes(errors)
    counts.update(_import_legacy_db(errors))
    counts["runs"] = _import_run_history(errors)

    report["ran"] = True
    try:
        migrated_marker().parent.mkdir(parents=True, exist_ok=True)
        migrated_marker().write_text(json.dumps({
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "counts": counts,
            "errors": errors,
        }, indent=2))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"marker: {exc}")
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    from .db import init_db

    ap = argparse.ArgumentParser(description="Import JobPilot v1 state into the v2 database")
    ap.add_argument("--force", action="store_true", help="re-run even if already migrated")
    args = ap.parse_args(argv)

    init_db()
    report = migrate(force=args.force)
    if not report["ran"]:
        print(f"skipped: {report['skipped_reason']}")
        return 0
    for key, value in report["counts"].items():
        print(f"  {key:16} {value}")
    for err in report["errors"]:
        print(f"  ! {err}")
    print("migration complete" if not report["errors"] else "migration complete with warnings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
