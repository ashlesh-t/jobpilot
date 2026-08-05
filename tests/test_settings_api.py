"""Profile, preferences, credential-vault and setup-status endpoints."""
from __future__ import annotations

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


@pytest.fixture()
def fake_vault(monkeypatch):
    """An in-memory credential store, so tests never touch the real keyring."""
    store: dict[str, str] = {}
    from core import secrets as secrets_lib

    monkeypatch.setattr(secrets_lib, "get", lambda user_id, key: store.get(key))
    monkeypatch.setattr(secrets_lib, "set", lambda user_id, key, value: (store.__setitem__(key, value), "keyring")[1])
    monkeypatch.setattr(secrets_lib, "reveal", lambda user_id, key: store.get(key))
    monkeypatch.setattr(secrets_lib, "has", lambda user_id, key: bool(store.get(key)))
    return store


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
def test_profile_skeleton_then_save_and_confirm(client):
    body = client.get("/api/profile").json()
    assert body["exists"] is False
    assert body["verified"] is False
    assert "interview_readiness" in body["profile"]

    client.put("/api/profile", json={"data": {"name": "Ada", "skills": ["Go"]}})
    assert client.get("/api/profile").json()["verified"] is False

    client.post("/api/profile/verify?confirm=true")
    after = client.get("/api/profile").json()
    assert after["verified"] is True
    assert after["profile"]["name"] == "Ada"


def test_profile_save_merges_rather_than_replaces(client):
    client.put("/api/profile", json={"data": {"name": "Ada", "skills": ["Go"]}})
    client.put("/api/profile", json={"data": {"email": "ada@example.com"}})
    profile = client.get("/api/profile").json()["profile"]
    assert profile["name"] == "Ada"          # not wiped by the second save
    assert profile["email"] == "ada@example.com"


def test_profile_export_keeps_the_json_file_in_sync(client, tmp_path):
    """The Layer B skills read cache/profile.json, so the DB write must mirror there."""
    import json

    client.put("/api/profile", json={"data": {"name": "Ada"}, "verified": True})
    on_disk = json.loads(
        (tmp_path / "users" / str(client.user_id) / "cache" / "profile.json").read_text())
    assert on_disk["name"] == "Ada"
    assert on_disk["profile_verified"] is True


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #
def test_preferences_round_trip_and_export(client, tmp_path):
    import json

    r = client.put("/api/preferences", json={
        "preferences": {"locations": ["Bengaluru"], "role_types": ["SWE"],
                        "score_threshold": 70}})
    assert r.status_code == 200
    prefs = client.get("/api/preferences").json()["preferences"]
    assert prefs["locations"] == ["Bengaluru"]
    assert prefs["score_threshold"] == 70

    exported = json.loads(
        (tmp_path / "users" / str(client.user_id) / "options" / "preferences.json").read_text())
    assert exported["role_types"] == ["SWE"]


def test_preferences_ignores_unknown_keys(client):
    client.put("/api/preferences", json={"preferences": {"nonsense_key": 1}})
    assert "nonsense_key" not in client.get("/api/preferences").json()["preferences"]


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def test_secret_list_never_returns_a_plaintext_value(client, fake_vault):
    fake_vault["ANTHROPIC_API_KEY"] = "sk-ant-supersecret-value-9f2a"

    body = client.get("/api/secrets").json()
    raw = client.get("/api/secrets").text
    entry = next(s for s in body["secrets"] if s["key"] == "ANTHROPIC_API_KEY")

    assert entry["set"] is True
    assert entry["masked"].endswith("9f2a")
    # The whole response body must not contain the secret anywhere.
    assert "supersecret" not in raw


def test_secret_write_and_explicit_reveal(client, fake_vault):
    r = client.put("/api/secrets/APIFY_TOKEN", json={"value": "apify_api_abcdef123456"})
    assert r.status_code == 200
    assert "abcdef" not in r.text          # the write response is masked too

    revealed = client.post("/api/secrets/APIFY_TOKEN/reveal").json()
    assert revealed["value"] == "apify_api_abcdef123456"


def test_reveal_missing_secret_is_404(client, fake_vault):
    assert client.post("/api/secrets/APIFY_TOKEN/reveal").status_code == 404


def test_unknown_secret_key_is_rejected(client, fake_vault):
    assert client.put("/api/secrets/NOT_A_KEY", json={"value": "x"}).status_code == 400
    assert client.post("/api/secrets/NOT_A_KEY/reveal").status_code == 400
    assert client.post("/api/secrets/NOT_A_KEY/test").status_code == 400


def test_empty_secret_is_rejected(client, fake_vault):
    assert client.put("/api/secrets/APIFY_TOKEN", json={"value": "   "}).status_code == 400


def test_test_endpoint_reports_unset(client, fake_vault):
    body = client.post("/api/secrets/APIFY_TOKEN/test").json()
    assert body["ok"] is False
    assert body["detail"] == "not set"


def test_telegram_chat_test_requires_the_bot_token(client, fake_vault):
    fake_vault["TELEGRAM_CHAT_ID"] = "12345"
    body = client.post("/api/secrets/TELEGRAM_CHAT_ID/test").json()
    assert body["ok"] is False
    assert "bot token" in body["detail"]


def test_adzuna_test_requires_both_keys(client, fake_vault):
    fake_vault["ADZUNA_APP_ID"] = "some-id"
    body = client.post("/api/secrets/ADZUNA_APP_ID/test").json()
    assert body["ok"] is False
    assert "ADZUNA_APP_KEY" in body["detail"]


def test_discord_test_rejects_a_non_webhook(client, fake_vault):
    fake_vault["DISCORD_WEBHOOK_URL"] = "https://example.com/hook"
    body = client.post("/api/secrets/DISCORD_WEBHOOK_URL/test").json()
    assert body["ok"] is False
    assert "webhook" in body["detail"]


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
def test_backend_listing_and_selection(client):
    body = client.get("/api/backends").json()
    ids = [b["id"] for b in body["backends"]]
    assert ids == ["claude_code", "claude_api", "gemini", "generic_cli"]
    assert "platform" in body["environment"]

    assert client.put("/api/backends", json={"backend": "claude_api"}).status_code == 200
    assert client.get("/api/backends").json()["selected"] == "claude_api"
    assert client.put("/api/backends", json={"backend": "nope"}).status_code == 400


# --------------------------------------------------------------------------- #
# Setup status
# --------------------------------------------------------------------------- #
def test_setup_status_reports_what_is_missing(client):
    body = client.get("/api/setup/status").json()
    assert body["ready"] is False
    assert "resume" in body["blocking"]
    assert "profile" in body["blocking"]
    assert "preferences" in body["blocking"]
    # Delivery is optional — no channel configured must not block a run.
    assert "notifications" not in body["blocking"]
    assert body["checks"]["database"]["ok"] is True


def test_setup_status_clears_as_things_are_configured(client, tmp_path, monkeypatch):
    from core.repo import resumes as resumes_repo

    resume = tmp_path / "cv.pdf"
    resume.write_bytes(b"%PDF-1.4 x")
    resumes_repo.add(client.user_id, resume, folder="main", make_active=True)

    client.put("/api/profile", json={"data": {"name": "Ada"}, "verified": True})
    client.put("/api/preferences", json={
        "preferences": {"locations": ["Pune"], "role_types": ["SWE"]}})

    # The AI backend is the only thing left, and it depends on the machine — assert the
    # three we control are green rather than asserting overall readiness.
    checks = client.get("/api/setup/status").json()["checks"]
    assert checks["resume"]["ok"] is True
    assert checks["profile"]["ok"] is True
    assert checks["preferences"]["ok"] is True
