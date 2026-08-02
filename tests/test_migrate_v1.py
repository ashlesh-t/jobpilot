"""v1 → v2 state migration tests.

Builds a synthetic v1 data directory (preferences.json, profile.json, jobs.sqlite,
cache/runs/*.json, resumes/base.pdf) and asserts every piece lands in the v2 database
without touching the originals.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

V1_SCHEMA = """
CREATE TABLE jobs_seen (
  job_id TEXT PRIMARY KEY, company TEXT, role TEXT, location TEXT, source TEXT,
  match_score REAL, resume_hash TEXT, first_seen TEXT, last_seen TEXT,
  tailored_resume_path TEXT, status TEXT DEFAULT 'active');
CREATE TABLE score_cache (
  job_id TEXT, resume_hash TEXT, score_json TEXT, computed_at TEXT,
  PRIMARY KEY (job_id, resume_hash));
CREATE TABLE user_feedback (
  job_id TEXT PRIMARY KEY, status TEXT, notes TEXT, feedback_date TEXT);
CREATE TABLE url_security_cache (
  url_hash TEXT PRIMARY KEY, url TEXT NOT NULL, risk_score INTEGER DEFAULT 0,
  risk_label TEXT DEFAULT 'unknown', is_allowlist INTEGER DEFAULT 0, final_url TEXT,
  redirect_hops TEXT, threats TEXT, checked_at TEXT, expires_at TEXT);
"""


@pytest.fixture()
def v1_dir(tmp_path, monkeypatch):
    """A populated v1 data directory with a fresh v2 database attached."""
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    (tmp_path / "options").mkdir(parents=True)
    (tmp_path / "cache" / "runs").mkdir(parents=True)
    (tmp_path / "resumes").mkdir(parents=True)

    (tmp_path / "options" / "preferences.json").write_text(json.dumps({
        "locations": ["Bengaluru", "Remote"],
        "score_threshold": 70,
        "schedule_slots_ist": ["09:30", {"name": "evening", "time": "18:00"}],
        "notify_channels": ["telegram", "discord"],
        "some_hand_added_key": "keep me",
    }))
    (tmp_path / "cache" / "profile.json").write_text(json.dumps({
        "name": "Ada Lovelace", "skills": ["Go", "Docker"], "experience_years": 2,
        "profile_verified": True, "hash": "abc123",
    }))
    (tmp_path / "cache" / "learning.json").write_text(json.dumps({
        "version": 1, "outcome_count": 7, "skill_weights": {"go": 1.15}}))
    (tmp_path / "cache" / "company_intel.json").write_text(json.dumps({
        "navi": {"archetype": "dsa-gate-product", "ttl_days": 45}}))
    (tmp_path / "cache" / "runs" / "20260715T093000.json").write_text(json.dumps({
        "id": "20260715T093000", "mode": "full", "engine": "claude_code",
        "status": "done", "started_at": "2026-07-15T09:30:00+00:00",
        "ended_at": "2026-07-15T09:44:00+00:00", "summary": "12 jobs",
    }))
    (tmp_path / "resumes" / "base.pdf").write_bytes(b"%PDF-1.4 base")
    (tmp_path / "resumes" / "old_cv.pdf").write_bytes(b"%PDF-1.4 old")

    db_path = tmp_path / "cache" / "jobs.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(V1_SCHEMA)
    conn.execute(
        "INSERT INTO jobs_seen VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("j1", "Swiss Re", "Golang Engineer", "Bengaluru", "linkedin", 78.0, "abc123",
         "2026-06-01T10:00:00+00:00", "2026-07-01T10:00:00+00:00", "", "active"))
    conn.execute(
        "INSERT INTO jobs_seen VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("j2", "Navi", "SDE-1", "Bengaluru", "naukri", 61.0, "abc123",
         "2026-06-10T10:00:00+00:00", "2026-07-02T10:00:00+00:00", "", "active"))
    conn.execute("INSERT INTO score_cache VALUES (?,?,?,?)", (
        "j1", "abc123", json.dumps({
            "score": 78.0, "keyword_score": 80, "semantic_score": 75,
            "matched_skills": ["Go", "Docker"], "missing_skills": ["Kafka"],
            "archetype": "gcc-enterprise", "source_board": "linkedin"}),
        "2026-07-01T10:00:00+00:00"))
    conn.execute("INSERT INTO user_feedback VALUES (?,?,?,?)",
                 ("j1", "interview", "round 1 done", "2026-07-05T10:00:00+00:00"))
    conn.execute("INSERT INTO url_security_cache VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("h1", "https://x.test", 10, "safe", 1, "https://x.test",
                  "[]", "[]", "2026-07-01T10:00:00+00:00", "2026-08-01T10:00:00+00:00"))
    conn.commit()
    conn.close()

    from core import db
    db.dispose()
    db.init_db()
    yield tmp_path
    db.dispose()


def test_migration_imports_every_source(v1_dir):
    from core import migrate_v1

    report = migrate_v1.migrate()
    assert report["ran"] is True
    assert report["errors"] == []

    c = report["counts"]
    assert c["profile"] == 1
    assert c["jobs"] == 2
    assert c["feedback"] == 1
    assert c["url_cache"] == 1
    assert c["runs"] == 1
    assert c["schedule_slots"] == 2
    assert c["resumes"] == 2
    assert c["json_caches"] == 2


def test_migration_preserves_values(v1_dir):
    from core import migrate_v1
    from core.repo import jobs, profiles, schedule, settings

    migrate_v1.migrate()

    prefs = settings.preferences()
    assert prefs["locations"] == ["Bengaluru", "Remote"]
    assert prefs["score_threshold"] == 70
    # Unrecognized v1 keys are preserved, not silently dropped.
    assert settings.get("legacy_preferences")["some_hand_added_key"] == "keep me"
    assert settings.get("learning")["outcome_count"] == 7

    prof = profiles.current()
    assert prof["name"] == "Ada Lovelace"
    assert prof["profile_verified"] is True
    assert prof["hash"] == "abc123"

    job = jobs.get("j1")
    assert job["score"] == 78.0
    assert job["matched_skills"] == ["Go", "Docker"]
    assert job["archetype"] == "gcc-enterprise"
    # first_seen must survive — otherwise every imported job looks brand new.
    assert job["first_seen"].startswith("2026-06-01")

    names = {s["name"]: s["time"] for s in schedule.list_all()}
    assert names == {"slot-1": "09:30", "evening": "18:00"}


def test_migration_activates_base_resume(v1_dir):
    from core import migrate_v1
    from core.repo import resumes

    migrate_v1.migrate()
    assert resumes.active()["filename"] == "base.pdf"


def test_migration_is_idempotent_and_non_destructive(v1_dir):
    from core import migrate_v1
    from core.repo import jobs

    first = migrate_v1.migrate()
    assert first["ran"] is True

    second = migrate_v1.migrate()
    assert second["ran"] is False
    assert "already migrated" in second["skipped_reason"]

    forced = migrate_v1.migrate(force=True)
    assert forced["ran"] is True
    assert forced["counts"]["jobs"] == 2          # updated, not duplicated
    assert jobs.query(include_stale=True)["total"] == 2

    # v1 sources are untouched.
    assert (v1_dir / "options" / "preferences.json").exists()
    assert (v1_dir / "cache" / "jobs.sqlite").exists()
    assert (v1_dir / "cache" / "profile.json").exists()


def test_migration_skips_when_no_v1_state(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)
    from core import db, migrate_v1

    db.dispose()
    db.init_db()
    report = migrate_v1.migrate()
    db.dispose()

    assert report["ran"] is False
    assert "no v1 state" in report["skipped_reason"]


def test_migration_survives_a_corrupt_source(v1_dir):
    from core import migrate_v1

    (v1_dir / "cache" / "profile.json").write_text("{ not json")
    report = migrate_v1.migrate()

    assert report["ran"] is True
    assert report["counts"]["profile"] == 0
    assert report["counts"]["jobs"] == 2          # the rest still imported
