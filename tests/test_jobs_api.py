"""Jobs / applications / scans / export API tests."""
from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from conftest import signup


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    from core import db
    db.dispose()
    db.init_db()

    import scheduler
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler.scheduler, "shutdown", lambda: None)

    import app as app_module
    with TestClient(app_module.app) as c:
        c.user_id = signup(c)["id"]
        yield c
    db.dispose()


def _seed(client, n: int = 3, **overrides):
    from core.repo import jobs as jobs_repo

    payload = []
    for i in range(n):
        job = {
            "job_id": f"job-{i}",
            "company": ["Acme", "Globex", "Initech"][i % 3],
            "role": "Backend Engineer",
            "location": ["Bengaluru", "Remote", "Pune"][i % 3],
            "source_board": ["linkedin", "remoteok", "naukri"][i % 3],
            "application_url": f"https://example.test/{i}",
            "score": 60 + i * 10,
            "keyword_score": 70,
            "semantic_score": 65,
            "location_weight": 1.0,
            "matched_skills": ["Go", "Docker"],
            "missing_skills": ["Kafka"],
            "market_salary": f"{8 + i * 4}-{12 + i * 4} LPA",
            "archetype": "gcc-enterprise",
        }
        job.update(overrides)
        payload.append(job)
    jobs_repo.upsert_scored(client.user_id, payload)
    return payload


# --------------------------------------------------------------------------- #
# Listing, sorting, filtering
# --------------------------------------------------------------------------- #
def test_jobs_list_is_paged_and_sorted(client):
    _seed(client, 3)
    body = client.get("/api/jobs?sort=score&order=desc").json()
    assert body["total"] == 3
    assert [j["score"] for j in body["items"]] == [80, 70, 60]
    assert body["pages"] == 1

    paged = client.get("/api/jobs?page_size=2").json()
    assert len(paged["items"]) == 2
    assert paged["pages"] == 2


def test_sort_by_package_uses_researched_salary(client):
    _seed(client, 3)
    body = client.get("/api/jobs?sort=package&order=desc").json()
    # 16-20 LPA is the top band; jobs with no researched salary must sort last, not first.
    assert body["items"][0]["salary_max_lpa"] == 20.0


def test_filters(client):
    _seed(client, 3)
    assert client.get("/api/jobs?min_score=70").json()["total"] == 2
    assert client.get("/api/jobs?sources=linkedin").json()["total"] == 1
    assert client.get("/api/jobs?search=globex").json()["total"] == 1
    # min_salary matches on the top of the range: a 12–16 LPA job is still a candidate
    # when you want at least 15.
    assert client.get("/api/jobs?min_salary=15").json()["total"] == 2
    assert client.get("/api/jobs?min_salary=19").json()["total"] == 1
    assert client.get("/api/jobs?locations=Remote").json()["total"] == 1


def test_stale_jobs_are_hidden_by_default(client):
    from datetime import timedelta

    from core.db import session_scope
    from core.models import Job, utcnow

    _seed(client, 2)
    with session_scope() as s:
        s.get(Job, "job-0").last_seen = utcnow() - timedelta(days=90)
    client.post("/api/jobs/refresh-stale")

    assert client.get("/api/jobs").json()["total"] == 1
    assert client.get("/api/jobs?include_stale=true").json()["total"] == 2


def test_facets_and_stats(client):
    _seed(client, 3)
    facets = client.get("/api/jobs/facets").json()
    assert set(facets["sources"]) == {"linkedin", "remoteok", "naukri"}
    assert "package" in facets["sortable"]

    stats = client.get("/api/jobs/stats").json()
    assert stats["total"] == 3
    assert stats["avg_score"] == 70.0
    assert sum(b["count"] for b in stats["score_buckets"]) == 3
    assert stats["funnel"]["total"] == 0
    assert "cost_month" in stats


def test_job_detail_includes_score_breakdown(client):
    _seed(client, 1)
    job = client.get("/api/jobs/job-0").json()
    assert job["matched_skills"] == ["Go", "Docker"]
    assert job["missing_skills"] == ["Kafka"]
    assert job["tailored"] == []
    assert client.get("/api/jobs/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
def test_apply_undo_and_status_flow(client):
    _seed(client, 1)

    applied = client.post("/api/jobs/job-0/apply", json={"note": "referred"}).json()
    assert applied["status"] == "applied"
    assert client.get("/api/jobs?applied_only=true").json()["total"] == 1

    moved = client.put("/api/jobs/job-0/application",
                       json={"status": "interview", "note": "round 1"}).json()
    assert moved["status"] == "interview"
    assert [h["status"] for h in moved["status_history"]] == ["applied", "interview"]

    board = client.get("/api/applications/board").json()
    assert len(board["columns"]["interview"]) == 1
    stages = {s["stage"]: s["count"] for s in board["funnel"]["stages"]}
    assert stages["applied"] == 1 and stages["interview"] == 1

    assert client.delete("/api/jobs/job-0/apply").status_code == 200
    assert client.get("/api/jobs?unapplied_only=true").json()["total"] == 1


def test_apply_rejects_unknown_job_and_bad_status(client):
    _seed(client, 1)
    assert client.post("/api/jobs/ghost/apply", json={}).status_code == 404
    client.post("/api/jobs/job-0/apply", json={})
    bad = client.put("/api/jobs/job-0/application", json={"status": "hired"})
    assert bad.status_code == 400


def test_undo_without_an_application_is_404(client):
    _seed(client, 1)
    assert client.delete("/api/jobs/job-0/apply").status_code == 404


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def test_csv_export_respects_the_current_filters(client):
    _seed(client, 3)
    res = client.get("/api/jobs/export?format=csv&min_score=70")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["#", "Company", "Role", "Location"]
    assert len(rows) == 3          # header + the 2 jobs scoring >= 70


def test_export_columns_match_the_emailed_report(client):
    """A user comparing the download to the Telegram spreadsheet must see the same
    columns — otherwise one of the two is quietly wrong."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from report_generator import COLUMNS

    _seed(client, 1)
    res = client.get("/api/jobs/export?format=csv")
    header = next(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    report_headers = [h for h, _k, _w in COLUMNS]
    assert header[: len(report_headers)] == report_headers


def test_xlsx_export(client):
    _seed(client, 2)
    res = client.get("/api/jobs/export?format=xlsx")
    assert res.status_code == 200
    assert res.content[:2] == b"PK"        # a real zip-based workbook
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats")


def test_export_includes_application_state(client):
    _seed(client, 1)
    client.post("/api/jobs/job-0/apply", json={})
    res = client.get("/api/jobs/export?format=csv")
    reader = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert "Application Status" in reader[0]
    assert "applied" in reader[1]


# --------------------------------------------------------------------------- #
# Scans
# --------------------------------------------------------------------------- #
def test_scan_listing_and_export(client):
    from core.repo import jobs as jobs_repo
    from core.repo import runs as runs_repo

    rid = runs_repo.new_run_id()
    runs_repo.create(client.user_id, rid, mode="native", engine="claude_code", phase_keys=["scrape"])
    scan_id = runs_repo.scan_id_for_run(client.user_id, rid)
    jobs_repo.upsert_scored(
        client.user_id,
        [{"job_id": "s1", "company": "Acme", "role": "SDE", "score": 80}],
        scan_id=scan_id)
    runs_repo.update_scan(client.user_id, rid, jobs_scored=1)

    scans = client.get("/api/scans").json()["scans"]
    assert scans[0]["id"] == scan_id
    assert scans[0]["jobs_scored"] == 1

    res = client.get(f"/api/scans/{scan_id}/export?format=csv")
    assert res.status_code == 200
    assert f"scan-{scan_id}" in res.headers["content-disposition"]

    assert client.get("/api/scans/9999/export").status_code == 404
