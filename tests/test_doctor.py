"""doctor.py's secret-backed checks must read this account's own store, not the
legacy machine-wide OS keyring / .env — regression guard for the bug where every
account saw someone else's (or nobody's) leftover Apify/Adzuna/Telegram/Discord
credentials as "valid"."""
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
        yield c
    db.dispose()


def _row(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_apify_check_ignores_the_legacy_keyring(client, monkeypatch):
    """Even with a real leftover value in the pre-multi-user store, a fresh account
    with nothing set of its own must show as not-configured."""
    import doctor

    user = signup(client, username="alice")
    monkeypatch.setattr(
        "jp_secrets.get_secret_optional",
        lambda key, default=None: "leaked-legacy-token" if key == "APIFY_TOKEN" else default,
    )

    rows = doctor.run_doctor(user["id"], live=False)["rows"]
    apify = _row(rows, "Apify")
    assert apify["status"] != "ok"
    assert "leaked-legacy-token" not in apify["detail"]


def test_apify_check_finds_this_users_own_token(client, monkeypatch):
    import doctor
    from core import secrets

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": {"username": "bob-on-apify"}}

    monkeypatch.setattr("requests.get", lambda url, params=None, timeout=None: _Resp())

    user = signup(client, username="bob")
    secrets.set(user["id"], "APIFY_TOKEN", "real-token-for-bob")

    rows = doctor.run_doctor(user["id"], live=False)["rows"]
    apify = _row(rows, "Apify")
    assert apify["status"] == "ok"


def test_second_account_does_not_see_the_firsts_secrets(client):
    """The core multi-tenant guarantee: doctor must never leak one account's
    credential status into another's."""
    import doctor
    from core import secrets

    alice = signup(client, username="alice2")
    secrets.set(alice["id"], "APIFY_TOKEN", "alices-token")

    client.post("/api/auth/logout")
    bob = signup(client, username="bob2")

    rows = doctor.run_doctor(bob["id"], live=False)["rows"]
    apify = _row(rows, "Apify")
    assert apify["status"] != "ok"
    assert "alices-token" not in apify["detail"]


def test_notifiers_check_ignores_the_legacy_keyring(client, monkeypatch):
    import doctor

    user = signup(client, username="carol")
    monkeypatch.setattr(
        "jp_secrets.get_secret_optional",
        lambda key, default=None: "leaked-legacy-value" if "TELEGRAM" in key else default,
    )

    rows = doctor.run_doctor(user["id"], live=False)["rows"]
    telegram = _row(rows, "Telegram")
    assert telegram["status"] != "ok"


def test_notifiers_check_finds_this_users_own_secrets(client):
    import doctor
    from core import secrets

    user = signup(client, username="dave")
    secrets.set(user["id"], "TELEGRAM_BOT_TOKEN", "123:abc")
    secrets.set(user["id"], "TELEGRAM_CHAT_ID", "999")

    rows = doctor.run_doctor(user["id"], live=False)["rows"]
    telegram = _row(rows, "Telegram")
    assert telegram["status"] == "ok"
