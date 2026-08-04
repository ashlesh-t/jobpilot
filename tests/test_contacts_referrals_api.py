"""HTTP routes for contacts (CRUD + bulk import) and draft-only referrals."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient


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
        yield c
    db.dispose()


def _seed_job(job_id="j1", company="Acme Corp"):
    from core.repo import jobs as jobs_repo
    jobs_repo.upsert_scored([{
        "job_id": job_id, "company": company, "role": "SWE", "location": "Remote",
        "score": 80, "application_url": "https://x.test",
    }])


# --------------------------------------------------------------------------- #
# Contacts CRUD
# --------------------------------------------------------------------------- #
def test_create_list_update_delete_contact(client):
    created = client.post("/api/contacts", json={
        "company": "Acme Corp", "name": "Jane HR", "email": "jane@acme.com", "role": "Recruiter",
    }).json()
    assert created["id"]

    listed = client.get("/api/contacts").json()["contacts"]
    assert len(listed) == 1

    updated = client.patch(f"/api/contacts/{created['id']}", json={"name": "Jane Doe"}).json()
    assert updated["name"] == "Jane Doe"

    assert client.delete(f"/api/contacts/{created['id']}").status_code == 200
    assert client.get("/api/contacts").json()["contacts"] == []


def test_update_unknown_contact_is_404(client):
    assert client.patch("/api/contacts/99999", json={"name": "x"}).status_code == 404


def test_delete_unknown_contact_is_404(client):
    assert client.delete("/api/contacts/99999").status_code == 404


# --------------------------------------------------------------------------- #
# CSV import
# --------------------------------------------------------------------------- #
def test_import_csv(client):
    csv_bytes = b"company,name,email,role\nAcme Corp,Jane HR,jane@acme.com,Recruiter\n,,,\n"
    r = client.post(
        "/api/contacts/import",
        files={"file": ("contacts.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1
    assert len(body["contacts"]) == 1


def test_import_rejects_unsupported_file_type(client):
    r = client.post(
        "/api/contacts/import",
        files={"file": ("contacts.txt", io.BytesIO(b"whatever"), "text/plain")},
    )
    assert r.status_code == 400


def test_import_empty_csv_is_a_400(client):
    r = client.post(
        "/api/contacts/import",
        files={"file": ("contacts.csv", io.BytesIO(b"company,name,email,role\n"), "text/csv")},
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Job detail attaches contacts + referrals
# --------------------------------------------------------------------------- #
def test_job_detail_includes_matching_contacts(client):
    _seed_job(company="Acme Corp")
    client.post("/api/contacts", json={"company": "ACME", "name": "Jane HR", "email": "jane@acme.com"})

    job = client.get("/api/jobs/j1").json()
    assert len(job["contacts"]) == 1
    assert job["contacts"][0]["name"] == "Jane HR"
    assert job["referrals"] == []


# --------------------------------------------------------------------------- #
# Referral status endpoint (generation itself needs a real engine — covered at the
# repo layer in test_referrals_repo.py; this only checks status transitions + 404s)
# --------------------------------------------------------------------------- #
def test_generate_referral_404s_for_unknown_job(client):
    r = client.post("/api/referrals/jobs/not-a-job", json={"contact_id": 1})
    assert r.status_code == 404


def test_generate_referral_404s_for_unknown_contact(client):
    _seed_job()
    r = client.post("/api/referrals/jobs/j1", json={"contact_id": 99999})
    assert r.status_code == 404


def test_set_status_on_unknown_referral_is_404(client):
    r = client.patch("/api/referrals/99999/status", json={"status": "sent"})
    assert r.status_code == 404


def test_set_invalid_status_is_400(client):
    from core.repo import contacts as contacts_repo
    from core.repo import referrals as referrals_repo

    _seed_job()
    contact = contacts_repo.create(company="Acme Corp", email="jane@acme.com")
    referral = referrals_repo.create("j1", contact["id"], message="hi")

    r = client.patch(f"/api/referrals/{referral['id']}/status", json={"status": "not-a-status"})
    assert r.status_code == 400


def test_referrals_for_job_endpoint(client):
    from core.repo import contacts as contacts_repo
    from core.repo import referrals as referrals_repo

    _seed_job()
    contact = contacts_repo.create(company="Acme Corp", email="jane@acme.com")
    referrals_repo.create("j1", contact["id"], message="hi")

    body = client.get("/api/referrals/jobs/j1").json()
    assert len(body["items"]) == 1
