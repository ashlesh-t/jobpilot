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


def test_schema_has_every_table(store):
    from sqlalchemy import inspect
    from core import db
    from core.models import ALL_TABLES

    names = set(inspect(db.get_engine()).get_table_names())
    for model in ALL_TABLES:
        assert model.__tablename__ in names


def test_settings_roundtrip_and_export(store):
    from core.repo import settings

    settings.update_preferences({"locations": ["Bengaluru", "Remote"], "score_threshold": 70})
    prefs = settings.preferences()
    assert prefs["locations"] == ["Bengaluru", "Remote"]
    assert prefs["score_threshold"] == 70
    # Layer A scripts read preferences.json directly, so it must stay in sync.
    import json
    exported = json.loads((store / "options" / "preferences.json").read_text())
    assert exported["locations"] == ["Bengaluru", "Remote"]


def test_settings_ignores_unknown_keys(store):
    from core.repo import settings

    settings.update_preferences({"locations": ["Pune"], "not_a_preference": 1})
    assert "not_a_preference" not in settings.preferences()


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


def test_upsert_and_query_jobs(store):
    from core.repo import jobs

    res = jobs.upsert_scored([_job("j1"), _job("j2", company="Globex", score=52.0,
                                              market_salary="6-9 LPA")])
    assert res == {"inserted": 2, "updated": 0}

    page = jobs.query(sort="score", order="desc")
    assert page["total"] == 2
    assert [i["job_id"] for i in page["items"]] == ["j1", "j2"]
    assert page["items"][0]["salary_max_lpa"] == 24.0

    # sort by package
    by_pkg = jobs.query(sort="package", order="asc")
    assert by_pkg["items"][0]["job_id"] == "j2"

    # filters
    assert jobs.query(min_score=60)["total"] == 1
    assert jobs.query(min_salary=10)["total"] == 1
    assert jobs.query(search="globex")["total"] == 1


def test_upsert_preserves_apply_url_and_updates(store):
    from core.repo import jobs

    jobs.upsert_scored([_job("j1")])
    res = jobs.upsert_scored([_job("j1", application_url="", score=88.0)])
    assert res == {"inserted": 0, "updated": 1}
    row = jobs.get("j1")
    assert row["application_url"] == "https://acme.test/apply"   # never blanked
    assert row["score"] == 88.0


def test_stale_marking_and_filter(store):
    from datetime import timedelta

    from core.db import session_scope
    from core.models import Job, utcnow
    from core.repo import jobs

    jobs.upsert_scored([_job("old"), _job("new")])
    with session_scope() as s:
        s.get(Job, "old").last_seen = utcnow() - timedelta(days=60)

    assert jobs.mark_stale(days=21) == 1
    assert jobs.query()["total"] == 1                       # stale hidden by default
    assert jobs.query(include_stale=True)["total"] == 2


def test_stale_marking_uses_deadline(store):
    from core.repo import jobs

    jobs.upsert_scored([_job("expired", last_date="2020-01-01")])
    assert jobs.mark_stale(days=999) == 1


def test_application_lifecycle(store):
    from core.repo import applications, jobs

    jobs.upsert_scored([_job("j1")])
    app = applications.mark_applied("j1", note="via referral")
    assert app["status"] == "applied"
    assert len(app["status_history"]) == 1

    # idempotent
    assert applications.mark_applied("j1")["id"] == app["id"]

    moved = applications.set_status("j1", "interview", note="round 1 scheduled")
    assert moved["status"] == "interview"
    assert [h["status"] for h in moved["status_history"]] == ["applied", "interview"]

    assert jobs.query(applied_only=True)["total"] == 1
    assert jobs.query(unapplied_only=True)["total"] == 0

    assert applications.unmark("j1") is True
    assert applications.get("j1") is None
    assert jobs.query(unapplied_only=True)["total"] == 1


def test_application_rejects_bad_status(store):
    from core.repo import applications, jobs

    jobs.upsert_scored([_job("j1")])
    applications.mark_applied("j1")
    with pytest.raises(ValueError):
        applications.set_status("j1", "hired")


def test_application_funnel_is_cumulative(store):
    from core.repo import applications, jobs

    jobs.upsert_scored([_job("a"), _job("b"), _job("c")])
    for jid in ("a", "b", "c"):
        applications.mark_applied(jid)
    applications.set_status("b", "interview")
    applications.set_status("c", "placed")

    f = applications.funnel()
    stages = {x["stage"]: x["count"] for x in f["stages"]}
    assert stages["applied"] == 3
    assert stages["interview"] == 2      # b (at interview) + c (already past it)
    assert stages["placed"] == 1


def test_run_phase_lifecycle_and_invalidate(store):
    from core.repo import runs

    rid = runs.new_run_id()
    runs.create(rid, mode="native", engine="claude_code",
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

    run = runs.get(rid)
    assert run["cost_usd"] == 0.01
    assert run["tokens_in"] == 100
    by_key = {p["key"]: p for p in run["phases"]}
    assert by_key["scrape"]["status"] == "done"
    assert by_key["scrape"]["artifact"] == {"count": 42}
    assert by_key["score"]["status"] == "pending"


def test_run_events_are_sequenced_and_persisted(store):
    from core.repo import runs

    rid = runs.new_run_id()
    runs.create(rid, mode="auto", engine="claude_code", phase_keys=["scrape"])
    for i in range(3):
        runs.add_event(rid, {"stage": "scrape", "msg": f"m{i}", "origin": "layerA"})

    evs = runs.events(rid)
    assert [e["seq"] for e in evs] == [1, 2, 3]
    assert runs.events(rid, after_seq=2)[0]["msg"] == "m2"


def test_reset_orphans_marks_interrupted_runs(store):
    from core.repo import runs

    rid = runs.new_run_id()
    runs.create(rid, mode="auto", engine="claude_code", phase_keys=["scrape"])
    runs.set_status(rid, "running")
    runs.phase_start(rid, "scrape")

    assert runs.reset_orphans() == 1
    run = runs.get(rid)
    assert run["status"] == "error"
    assert run["phases"][0]["status"] == "cancelled"


def test_resume_upload_activation_and_removal(store, tmp_path):
    from core.repo import resumes

    src = tmp_path / "my_cv.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    first = resumes.add(src, folder="2026")
    assert first["is_active"] is True                 # first upload auto-activates

    src2 = tmp_path / "other.pdf"
    src2.write_bytes(b"%PDF-1.4 other")
    second = resumes.add(src2, folder="2026")
    assert second["is_active"] is False

    resumes.set_active(second["id"])
    assert resumes.active()["id"] == second["id"]

    resumes.remove(second["id"])
    assert resumes.active()["id"] == first["id"]      # activation falls back


def test_resume_rejects_unsupported_type(store, tmp_path):
    from core.repo import resumes

    bad = tmp_path / "resume.exe"
    bad.write_bytes(b"nope")
    with pytest.raises(ValueError):
        resumes.add(bad)


def test_profile_save_exports_json_and_resets_verification(store):
    import json

    from core.repo import profiles

    profiles.save({"name": "Ada Lovelace", "skills": ["Go"]}, verified=True,
                  resume_hash="hash-a")
    assert profiles.is_verified() is True
    on_disk = json.loads((store / "cache" / "profile.json").read_text())
    assert on_disk["name"] == "Ada Lovelace"
    assert on_disk["profile_verified"] is True

    # New resume hash invalidates the human verification.
    profiles.save({}, resume_hash="hash-b")
    assert profiles.is_verified() is False
    assert profiles.current()["name"] == "Ada Lovelace"   # merge, not replace


def test_tailored_naming_and_upsert(store):
    from core.repo import jobs, tailored

    assert tailored.resume_basename("ashlesh tiwari") == "Ashlesh_Tiwari_Resume"
    assert tailored.folder_name("abc123", "Swiss Re") == "abc123-SwissRe"

    jobs.upsert_scored([_job("abc123", company="Swiss Re")])
    rec = tailored.upsert("abc123", company="Swiss Re", pdf_path="/x/a.pdf",
                          ats_before=60, ats_after=82, engine="claude_code")
    assert rec["folder_name"] == "abc123-SwissRe"
    assert tailored.count() == 1

    again = tailored.upsert("abc123", company="Swiss Re", tex_path="/x/a.tex")
    assert again["id"] == rec["id"]           # same folder → same row
    assert again["pdf_path"] == "/x/a.pdf"    # earlier value preserved


def test_cost_summary_separates_subscription_tokens(store):
    from core.repo import cost

    cost.record(engine="claude_api", model="claude-opus-5", tokens_in=1000,
                tokens_out=500, usd=0.12, run_id="r1", phase_key="score")
    cost.record(engine="claude_code", tokens_in=4000, tokens_out=900, usd=0.0,
                source="subscription", run_id="r1", phase_key="scrape")

    s = cost.summary(run_id="r1")
    assert s["usd"] == 0.12
    assert s["tokens_in"] == 5000
    assert s["subscription_tokens"] == 4900
    assert len(cost.for_run("r1")) == 2


def test_schedule_slot_crud_and_unique_names(store):
    from core.repo import schedule

    a = schedule.create(name="morning", time="09:30")
    b = schedule.create(name="morning", time="14:00")
    assert b["name"] == "morning-2"

    schedule.update(a["id"], time="10:00", enabled=False)
    assert schedule.get(a["id"])["time"] == "10:00"
    assert len(schedule.list_all(enabled_only=True)) == 1

    with pytest.raises(ValueError):
        schedule.create(name="bad", time="25:00")

    assert schedule.delete(b["id"]) is True
    assert len(schedule.list_all()) == 1


def test_missed_slots_returns_one_catchup_per_slot(store):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from core.repo import schedule

    tz = ZoneInfo("Asia/Kolkata")
    # "Now" is 11:00 IST; a 09:30 slot fired 1.5h ago and was never served.
    now = datetime(2026, 8, 1, 11, 0, tzinfo=tz)
    schedule.create(name="morning", time="09:30")
    schedule.create(name="evening", time="18:00")

    due = schedule.missed_since_downtime(grace_hours=6, now=now)
    assert [d["name"] for d in due] == ["morning"]

    # Outside the grace window → skipped rather than a surprise run.
    assert schedule.missed_since_downtime(grace_hours=1, now=now) == []

    # Already served → not due again.
    schedule.record_fire(due[0]["id"], run_id="r1", when=now)
    later = now + timedelta(minutes=5)
    assert schedule.missed_since_downtime(grace_hours=6, now=later) == []
