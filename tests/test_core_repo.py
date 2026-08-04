"""Core data-layer tests — schema, settings, jobs, applications, runs, resumes, cost."""
from __future__ import annotations

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A throwaway JobPilot data dir with a fresh database.

    Defaults to SQLite. Set $JOBPILOT_TEST_DATABASE_URL to run the identical suite
    against a real Postgres — the point of the single-code-path design is that every
    assertion here must hold on both backends.
    """
    import os

    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    pg = os.environ.get("JOBPILOT_TEST_DATABASE_URL")
    if pg:
        monkeypatch.setenv("JOBPILOT_DATABASE_URL", pg)
    else:
        monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    from core import db
    from core.models import Base

    db.dispose()
    if pg:
        Base.metadata.drop_all(db.get_engine())
        with db.get_engine().begin() as conn:
            from sqlalchemy import text
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    db.init_db()
    yield tmp_path
    db.dispose()


@pytest.fixture()
def user_id(store):
    """A real account row — every repo function now scopes its query to one."""
    from core.repo import users as users_repo
    return users_repo.create(username="tester", password="testpass123")["id"]


def test_schema_has_every_table(store):
    from sqlalchemy import inspect
    from core import db
    from core.models import ALL_TABLES

    names = set(inspect(db.get_engine()).get_table_names())
    for model in ALL_TABLES:
        assert model.__tablename__ in names


def test_settings_roundtrip_and_export(store, user_id):
    from core.repo import settings

    settings.update_preferences(user_id, {"locations": ["Bengaluru", "Remote"], "score_threshold": 70})
    prefs = settings.preferences(user_id)
    assert prefs["locations"] == ["Bengaluru", "Remote"]
    assert prefs["score_threshold"] == 70
    # Layer A scripts read preferences.json directly, so it must stay in sync.
    import json
    exported = json.loads(
        (store / "users" / str(user_id) / "options" / "preferences.json").read_text())
    assert exported["locations"] == ["Bengaluru", "Remote"]


def test_settings_ignores_unknown_keys(store, user_id):
    from core.repo import settings

    settings.update_preferences(user_id, {"locations": ["Pune"], "not_a_preference": 1})
    assert "not_a_preference" not in settings.preferences(user_id)


def test_pipeline_phase_config_defaults_every_phase(store, user_id):
    from core.repo import settings

    cfg = settings.pipeline_phase_config(user_id)
    from orchestrator import phases as P
    assert set(cfg) == set(P.PHASE_KEYS)
    assert all(entry == {"enabled": True, "model": None} for entry in cfg.values())
    # A python phase's model is always None even if something stray got stored there.
    assert cfg["scrape"]["model"] is None


def test_pipeline_phase_config_rejects_an_unknown_phase(store, user_id):
    from core.repo import settings

    import pytest as pt
    with pt.raises(ValueError):
        settings.set_pipeline_phase_config(user_id, {"not-a-real-phase": {"enabled": True}})


def test_pipeline_phase_config_persists_a_choice(store, user_id):
    from core.repo import settings

    settings.set_pipeline_phase_config(user_id, {"discover": {"enabled": False, "model": "haiku"}})
    cfg = settings.pipeline_phase_config(user_id)
    assert cfg["discover"] == {"enabled": False, "model": "haiku"}
    # Untouched phases keep their defaults.
    assert cfg["score"] == {"enabled": True, "model": None}


def test_enabled_phase_keys_always_includes_required_phases(store, user_id):
    """discover/intel/salary/notify are optional; everything else is required and
    must run regardless of what's stored — a bad config should never silently break
    the pipeline by dropping a hard dependency."""
    from core.repo import settings

    settings.set_pipeline_phase_config(user_id, {
        "discover": {"enabled": False},
        "scrape": {"enabled": False},  # required — must be ignored
    })
    keys = settings.enabled_phase_keys(user_id)
    assert "scrape" in keys
    assert "discover" not in keys


def test_upgrade_migrates_stale_accept_edits_default(store, user_id):
    """Anyone who ran `jobpilot setup` before the bypassPermissions default existed has
    the old value baked into their settings row, with no UI to change it by hand —
    migration 0002 must fix it silently on the very next `jobpilot start`/`serve`,
    with no manual step, since that's how every existing install actually upgrades."""
    from alembic import command
    from core import db
    from core.migrations import alembic_config
    from core.repo import settings as settings_repo

    # Simulate an install that predates migration 0002: rewind the tracked revision
    # and write the settings row the way the old default would have.
    cfg = alembic_config(db.get_engine().url.render_as_string(hide_password=False))
    cfg.attributes["connection"] = db.get_engine()
    command.stamp(cfg, "0001_initial")
    settings_repo.set(user_id, "engine", {"provider": "claude_code", "model": "",
                                 "permission_mode": "acceptEdits"}, export=False)

    db.init_db()  # what every `jobpilot start`/`serve` already calls

    assert settings_repo.engine_config(user_id)["permission_mode"] == "bypassPermissions"


@pytest.mark.parametrize("text,expected", [
    ("12-18 LPA", (12.0, 18.0)),
    ("₹15 LPA", (15.0, 15.0)),
    ("8 – 12 lakhs", (8.0, 12.0)),
    ("competitive", (None, None)),
    ("", (None, None)),
])
def test_parse_salary_lpa(text, expected):
    from core.repo.jobs import parse_salary_lpa

    assert parse_salary_lpa(text) == expected


def _job(job_id="j1", **kw):
    base = {
        "job_id": job_id, "company": "Acme", "role": "Backend Engineer",
        "location": "Bengaluru", "source_board": "linkedin",
        "application_url": "https://acme.test/apply", "score": 78.0,
        "keyword_score": 80, "semantic_score": 75, "location_weight": 1.0,
        "matched_skills": ["Go", "Docker"], "market_salary": "18-24 LPA",
    }
    base.update(kw)
    return base


def test_upsert_and_query_jobs(store, user_id):
    from core.repo import jobs

    res = jobs.upsert_scored(user_id, [_job("j1"), _job("j2", company="Globex", score=52.0,
                                              market_salary="6-9 LPA")])
    assert res == {"inserted": 2, "updated": 0}

    page = jobs.query(user_id, sort="score", order="desc")
    assert page["total"] == 2
    assert [i["job_id"] for i in page["items"]] == ["j1", "j2"]
    assert page["items"][0]["salary_max_lpa"] == 24.0

    # sort by package
    by_pkg = jobs.query(user_id, sort="package", order="asc")
    assert by_pkg["items"][0]["job_id"] == "j2"

    # filters
    assert jobs.query(user_id, min_score=60)["total"] == 1
    assert jobs.query(user_id, min_salary=10)["total"] == 1
    assert jobs.query(user_id, search="globex")["total"] == 1


def test_upsert_preserves_apply_url_and_updates(store, user_id):
    from core.repo import jobs

    jobs.upsert_scored(user_id, [_job("j1")])
    res = jobs.upsert_scored(user_id, [_job("j1", application_url="", score=88.0)])
    assert res == {"inserted": 0, "updated": 1}
    row = jobs.get(user_id, "j1")
    assert row["application_url"] == "https://acme.test/apply"   # never blanked
    assert row["score"] == 88.0


def test_stale_marking_and_filter(store, user_id):
    from datetime import timedelta

    from core.db import session_scope
    from core.models import Job, utcnow
    from core.repo import jobs

    jobs.upsert_scored(user_id, [_job("old"), _job("new")])
    with session_scope() as s:
        s.get(Job, "old").last_seen = utcnow() - timedelta(days=60)

    assert jobs.mark_stale(user_id, days=21) == 1
    assert jobs.query(user_id)["total"] == 1                       # stale hidden by default
    assert jobs.query(user_id, include_stale=True)["total"] == 2


def test_stale_marking_uses_deadline(store, user_id):
    from core.repo import jobs

    jobs.upsert_scored(user_id, [_job("expired", last_date="2020-01-01")])
    assert jobs.mark_stale(user_id, days=999) == 1


def test_application_lifecycle(store, user_id):
    from core.repo import applications, jobs

    jobs.upsert_scored(user_id, [_job("j1")])
    app = applications.mark_applied(user_id, "j1", note="via referral")
    assert app["status"] == "applied"
    assert len(app["status_history"]) == 1

    # idempotent
    assert applications.mark_applied(user_id, "j1")["id"] == app["id"]

    moved = applications.set_status(user_id, "j1", "interview", note="round 1 scheduled")
    assert moved["status"] == "interview"
    assert [h["status"] for h in moved["status_history"]] == ["applied", "interview"]

    assert jobs.query(user_id, applied_only=True)["total"] == 1
    assert jobs.query(user_id, unapplied_only=True)["total"] == 0

    assert applications.unmark(user_id, "j1") is True
    assert applications.get(user_id, "j1") is None
    assert jobs.query(user_id, unapplied_only=True)["total"] == 1


def test_application_rejects_bad_status(store, user_id):
    from core.repo import applications, jobs

    jobs.upsert_scored(user_id, [_job("j1")])
    applications.mark_applied(user_id, "j1")
    with pytest.raises(ValueError):
        applications.set_status(user_id, "j1", "hired")


def test_application_funnel_is_cumulative(store, user_id):
    from core.repo import applications, jobs

    jobs.upsert_scored(user_id, [_job("a"), _job("b"), _job("c")])
    for jid in ("a", "b", "c"):
        applications.mark_applied(user_id, jid)
    applications.set_status(user_id, "b", "interview")
    applications.set_status(user_id, "c", "placed")

    f = applications.funnel(user_id)
    stages = {x["stage"]: x["count"] for x in f["stages"]}
    assert stages["applied"] == 3
    assert stages["interview"] == 2      # b (at interview) + c (already past it)
    assert stages["placed"] == 1


def test_run_phase_lifecycle_and_invalidate(store, user_id):
    from core.repo import runs

    rid = runs.new_run_id()
    runs.create(user_id, rid, mode="native", engine="claude_code",
                phase_keys=["scrape", "filter", "score", "report"])

    runs.phase_start(rid, "scrape")
    runs.phase_finish(rid, "scrape", "done", artifact={"count": 42}, cost_usd=0.01,
                      tokens_in=100, tokens_out=50)
    runs.phase_start(rid, "filter")
    runs.phase_finish(rid, "filter", "done")
    runs.phase_start(rid, "score")
    runs.phase_finish(rid, "score", "done")

    assert runs.first_incomplete(rid) == "report"

    reset = runs.invalidate_from(rid, "score")
    assert reset == ["score", "report"]
    assert runs.first_incomplete(rid) == "score"

    run = runs.get(user_id, rid)
    assert run["cost_usd"] == 0.01
    assert run["tokens_in"] == 100
    by_key = {p["key"]: p for p in run["phases"]}
    assert by_key["scrape"]["status"] == "done"
    assert by_key["scrape"]["artifact"] == {"count": 42}
    assert by_key["score"]["status"] == "pending"


def test_run_events_are_sequenced_and_persisted(store, user_id):
    from core.repo import runs

    rid = runs.new_run_id()
    runs.create(user_id, rid, mode="auto", engine="claude_code", phase_keys=["scrape"])
    for i in range(3):
        runs.add_event(rid, {"stage": "scrape", "msg": f"m{i}", "origin": "layerA"})

    evs = runs.events(rid)
    assert [e["seq"] for e in evs] == [1, 2, 3]
    assert runs.events(rid, after_seq=2)[0]["msg"] == "m2"


def test_reset_orphans_marks_interrupted_runs(store, user_id):
    from core.repo import runs

    rid = runs.new_run_id()
    runs.create(user_id, rid, mode="auto", engine="claude_code", phase_keys=["scrape"])
    runs.set_status(user_id, rid, "running")
    runs.phase_start(rid, "scrape")

    assert runs.reset_orphans() == 1
    run = runs.get(user_id, rid)
    assert run["status"] == "error"
    assert run["phases"][0]["status"] == "cancelled"


def test_resume_upload_activation_and_removal(store, user_id, tmp_path):
    from core.repo import resumes

    src = tmp_path / "my_cv.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    first = resumes.add(user_id, src, folder="2026")
    assert first["is_active"] is True                 # first upload auto-activates

    src2 = tmp_path / "other.pdf"
    src2.write_bytes(b"%PDF-1.4 other")
    second = resumes.add(user_id, src2, folder="2026")
    assert second["is_active"] is False

    resumes.set_active(user_id, second["id"])
    assert resumes.active(user_id)["id"] == second["id"]

    resumes.remove(user_id, second["id"])
    assert resumes.active(user_id)["id"] == first["id"]      # activation falls back


def test_resume_rejects_unsupported_type(store, user_id, tmp_path):
    from core.repo import resumes

    bad = tmp_path / "resume.exe"
    bad.write_bytes(b"nope")
    with pytest.raises(ValueError):
        resumes.add(user_id, bad)


def test_profile_save_exports_json_and_resets_verification(store, user_id):
    import json

    from core.repo import profiles

    profiles.save(user_id, {"name": "Ada Lovelace", "skills": ["Go"]}, verified=True,
                  resume_hash="hash-a")
    assert profiles.is_verified(user_id) is True
    on_disk = json.loads(
        (store / "users" / str(user_id) / "cache" / "profile.json").read_text())
    assert on_disk["name"] == "Ada Lovelace"
    assert on_disk["profile_verified"] is True

    # New resume hash invalidates the human verification.
    profiles.save(user_id, {}, resume_hash="hash-b")
    assert profiles.is_verified(user_id) is False
    assert profiles.current(user_id)["name"] == "Ada Lovelace"   # merge, not replace


def test_tailored_naming_and_upsert(store, user_id):
    from core.repo import jobs, tailored

    assert tailored.resume_basename("ashlesh tiwari") == "Ashlesh_Tiwari_Resume"
    assert tailored.folder_name("abc123", "Swiss Re") == "abc123-SwissRe"

    jobs.upsert_scored(user_id, [_job("abc123", company="Swiss Re")])
    rec = tailored.upsert(user_id, "abc123", company="Swiss Re", pdf_path="/x/a.pdf",
                          ats_before=60, ats_after=82, engine="claude_code")
    assert rec["folder_name"] == "abc123-SwissRe"
    assert tailored.count(user_id) == 1

    again = tailored.upsert(user_id, "abc123", company="Swiss Re", tex_path="/x/a.tex")
    assert again["id"] == rec["id"]           # same folder → same row
    assert again["pdf_path"] == "/x/a.pdf"    # earlier value preserved


def test_cost_summary_separates_subscription_tokens(store, user_id):
    from core.repo import cost

    cost.record(user_id, engine="claude_api", model="claude-opus-5", tokens_in=1000,
                tokens_out=500, usd=0.12, run_id="r1", phase_key="score")
    cost.record(user_id, engine="claude_code", tokens_in=4000, tokens_out=900, usd=0.0,
                source="subscription", run_id="r1", phase_key="scrape")

    s = cost.summary(user_id, run_id="r1")
    assert s["usd"] == 0.12
    assert s["tokens_in"] == 5000
    assert s["subscription_tokens"] == 4900
    assert len(cost.for_run(user_id, "r1")) == 2


def test_schedule_slot_crud_and_unique_names(store, user_id):
    from core.repo import schedule

    a = schedule.create(user_id, name="morning", time="09:30")
    b = schedule.create(user_id, name="morning", time="14:00")
    assert b["name"] == "morning-2"

    schedule.update(user_id, a["id"], time="10:00", enabled=False)
    assert schedule.get(user_id, a["id"])["time"] == "10:00"
    assert len(schedule.list_all(user_id, enabled_only=True)) == 1

    with pytest.raises(ValueError):
        schedule.create(user_id, name="bad", time="25:00")

    assert schedule.delete(user_id, b["id"]) is True
    assert len(schedule.list_all(user_id)) == 1


def test_missed_slots_returns_one_catchup_per_slot(store, user_id):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from core.repo import schedule

    tz = ZoneInfo("Asia/Kolkata")
    # "Now" is 11:00 IST; a 09:30 slot fired 1.5h ago and was never served.
    now = datetime(2026, 8, 1, 11, 0, tzinfo=tz)
    schedule.create(user_id, name="morning", time="09:30")
    schedule.create(user_id, name="evening", time="18:00")

    due = schedule.missed_since_downtime(user_id, grace_hours=6, now=now)
    assert [d["name"] for d in due] == ["morning"]

    # Outside the grace window → skipped rather than a surprise run.
    assert schedule.missed_since_downtime(user_id, grace_hours=1, now=now) == []

    # Already served → not due again.
    schedule.record_fire(user_id, due[0]["id"], run_id="r1", when=now)
    later = now + timedelta(minutes=5)
    assert schedule.missed_since_downtime(user_id, grace_hours=6, now=later) == []
