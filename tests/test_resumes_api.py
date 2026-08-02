"""Resume upload, folders, activation, deletion and profile extraction."""
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


def _upload(client, name="cv.txt", body=b"Ada Lovelace\nada@example.com\nPython, Docker",
            folder="default", make_active=True):
    return client.post(
        "/api/resumes/upload",
        files={"file": (name, io.BytesIO(body), "text/plain")},
        data={"folder": folder, "make_active": str(make_active).lower()},
    )


# --------------------------------------------------------------------------- #
# Upload / activation
# --------------------------------------------------------------------------- #
def test_first_upload_becomes_active(client):
    r = _upload(client)
    assert r.status_code == 200
    resume = r.json()["resume"]
    assert resume["is_active"] is True
    assert resume["folder"] == "default"

    listing = client.get("/api/resumes").json()
    assert listing["active"]["id"] == resume["id"]
    assert listing["folders"][0]["folder"] == "default"


def test_active_resume_is_written_into_preferences(client):
    """Layer A reads resume_hash to decide when the score cache is stale."""
    _upload(client)
    prefs = client.get("/api/preferences").json()["preferences"]
    assert prefs["resume_path"].endswith("cv.txt")
    assert len(prefs["resume_hash"]) == 64


def test_only_one_resume_is_active_at_a_time(client):
    first = _upload(client, name="one.txt").json()["resume"]
    second = _upload(client, name="two.txt", make_active=False).json()["resume"]
    assert second["is_active"] is False

    client.post(f"/api/resumes/{second['id']}/activate")
    listing = client.get("/api/resumes").json()
    active = [r for r in listing["resumes"] if r["is_active"]]
    assert len(active) == 1
    assert active[0]["id"] == second["id"]
    assert first["id"] != active[0]["id"]


def test_folders_group_resumes(client):
    _upload(client, name="a.txt", folder="2026")
    _upload(client, name="b.txt", folder="backend", make_active=False)
    folders = {f["folder"] for f in client.get("/api/resumes").json()["folders"]}
    assert folders == {"2026", "backend"}


def test_folder_rename_moves_the_files(client):
    _upload(client, name="a.txt", folder="old")
    r = client.post("/api/resumes/folders/rename", json={"old": "old", "new": "new"})
    assert r.json()["moved"] == 1
    resume = client.get("/api/resumes").json()["resumes"][0]
    assert resume["folder"] == "new"
    assert resume["missing"] is False       # the path was updated with the move


def test_unsupported_file_type_is_rejected(client):
    r = client.post(
        "/api/resumes/upload",
        files={"file": ("resume.exe", io.BytesIO(b"nope"), "application/octet-stream")},
        data={"folder": "default"},
    )
    assert r.status_code == 400
    assert "supported" in r.json()["detail"]


def test_oversized_upload_is_rejected(client):
    big = b"x" * (16 * 1024 * 1024)
    r = client.post(
        "/api/resumes/upload",
        files={"file": ("big.txt", io.BytesIO(big), "text/plain")},
        data={"folder": "default"},
    )
    assert r.status_code == 413


def test_delete_falls_back_to_another_active_resume(client):
    first = _upload(client, name="one.txt").json()["resume"]
    second = _upload(client, name="two.txt", make_active=False).json()["resume"]

    body = client.delete(f"/api/resumes/{second['id']}").json()
    assert body["active"]["id"] == first["id"]

    body = client.delete(f"/api/resumes/{first['id']}").json()
    assert body["active"] is None
    assert client.delete(f"/api/resumes/{first['id']}").status_code == 404


def test_download_returns_the_file(client):
    resume = _upload(client, body=b"hello resume").json()["resume"]
    r = client.get(f"/api/resumes/{resume['id']}/download")
    assert r.status_code == 200
    assert b"hello resume" in r.content


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def test_extraction_falls_back_to_heuristics_without_an_agent(client, monkeypatch):
    import engines

    def unavailable(*_a, **_k):
        raise RuntimeError("no backend configured")

    monkeypatch.setattr(engines, "get_engine", unavailable)

    resume = _upload(
        client,
        body=b"Ada Lovelace\nada@example.com\n+919876543210\n"
             b"Skills: Python, Docker, Kubernetes, Kafka\n"
             b"https://github.com/ada",
    ).json()["resume"]

    body = client.post(f"/api/resumes/{resume['id']}/extract").json()
    assert body["source"] == "heuristic"
    assert "check every field" in body["detail"]

    profile = body["profile"]
    assert profile["email"] == "ada@example.com"
    assert "Python" in profile["skills"]
    assert "Kubernetes" in profile["skills"]
    assert profile["github_url"] == "https://github.com/ada"
    # Extraction never auto-confirms — a human has to look at it.
    assert profile["profile_verified"] is False


def test_extraction_uses_the_agent_when_available(client, monkeypatch):
    import engines
    from engines.base import RunResult

    class FakeEngine:
        def available(self):
            return True, ""

        async def run(self, program, run_id, on_event):
            assert "RESUME:" in program
            return RunResult(ok=True, artifacts={
                "final_text": '{"name": "Ada Lovelace", "skills": ["Go"], '
                              '"experience_years": 3}'})

        async def stop(self):
            pass

    monkeypatch.setattr(engines, "get_engine", lambda *a, **k: FakeEngine())

    resume = _upload(client).json()["resume"]
    body = client.post(f"/api/resumes/{resume['id']}/extract").json()
    assert body["source"] == "agent"
    assert body["profile"]["name"] == "Ada Lovelace"
    assert body["profile"]["skills"] == ["Go"]


def test_extraction_reports_an_unreadable_file(client, monkeypatch):
    resume = _upload(client, name="scan.pdf", body=b"%PDF-1.4 not real").json()["resume"]
    r = client.post(f"/api/resumes/{resume['id']}/extract")
    assert r.status_code == 422
    assert "scanned image" in r.json()["detail"]


def test_extract_unknown_resume_is_404(client):
    assert client.post("/api/resumes/999/extract").status_code == 404


# --------------------------------------------------------------------------- #
# Setup gate
# --------------------------------------------------------------------------- #
def test_uploading_a_resume_clears_that_setup_blocker(client):
    assert "resume" in client.get("/api/setup/status").json()["blocking"]
    _upload(client)
    assert "resume" not in client.get("/api/setup/status").json()["blocking"]
