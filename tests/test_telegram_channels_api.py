"""HTTP routes for Telegram channel management — isolated from the real repo config."""
from __future__ import annotations

import json

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

    # The channel list is repo-config, not user-data (same tier as
    # config/target_companies.json) — point it at a throwaway file so tests never
    # touch the real config/telegram_channels.json.
    import telegram_channels as tc
    cfg_path = tmp_path / "telegram_channels.json"
    cfg_path.write_text(json.dumps({"enabled": True, "channels": []}))
    monkeypatch.setattr(tc, "_config_path", lambda: cfg_path)

    import app as app_module
    with TestClient(app_module.app) as c:
        yield c
    db.dispose()


def test_list_channels_starts_empty(client):
    assert client.get("/api/telegram-channels").json()["channels"] == []


def test_add_rejects_an_invalid_channel(client, monkeypatch):
    import telegram_channels as tc
    monkeypatch.setattr(tc, "_fetch_preview_page",
                        lambda channel, before=None: "<html>no messages</html>")
    r = client.post("/api/telegram-channels", json={"username": "fakechannel"})
    assert r.status_code == 422
    assert client.get("/api/telegram-channels").json()["channels"] == []


def test_add_and_remove_a_valid_channel(client, monkeypatch):
    import telegram_channels as tc
    sample = '''<div data-post="realchannel/1">
      <div class="tgme_widget_message_text js-message_text" dir="auto">A real job post</div>
    </div>'''
    monkeypatch.setattr(tc, "_fetch_preview_page", lambda channel, before=None: sample)

    r = client.post("/api/telegram-channels", json={"username": "realchannel"})
    assert r.status_code == 200
    assert r.json()["valid"] is True
    assert [c["username"] for c in client.get("/api/telegram-channels").json()["channels"]] == ["realchannel"]

    r = client.delete("/api/telegram-channels/realchannel")
    assert r.status_code == 200
    assert client.get("/api/telegram-channels").json()["channels"] == []


def test_remove_unknown_channel_is_404(client):
    assert client.delete("/api/telegram-channels/nope").status_code == 404
