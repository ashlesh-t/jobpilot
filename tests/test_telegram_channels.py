"""scripts/scrapers/telegram_channels.py — parsing + config management, no network."""
from __future__ import annotations

import json

import telegram_channels as tc

SAMPLE_PAGE = '''
<div class="tgme_widget_message" data-post="getjobss/100">
  <div class="tgme_widget_message_text js-message_text" dir="auto">Company A | Backend Engineer | Bengaluru</div>
  <a class="tgme_widget_message_date" href="x"><time datetime="2026-08-01T10:00:00+00:00"/></a>
</div>
<div class="tgme_widget_message" data-post="getjobss/101">
  <div class="tgme_widget_message_text js-message_text" dir="auto">Some unrelated chit-chat message with no job.</div>
  <a class="tgme_widget_message_date" href="x"><time datetime="2026-08-02T10:00:00+00:00"/></a>
</div>
'''

EMPTY_PAGE = "<html><body>no messages here</body></html>"


def test_parse_preview_html_extracts_messages_in_order():
    messages = tc._parse_preview_html(SAMPLE_PAGE)
    assert [m[0] for m in messages] == [100, 101]
    assert "Company A" in messages[0][1]
    assert messages[0][2] == "2026-08-01T10:00:00+00:00"


def test_parse_preview_html_returns_empty_for_no_messages():
    assert tc._parse_preview_html(EMPTY_PAGE) == []


def test_validate_channel_rejects_empty_page(monkeypatch):
    monkeypatch.setattr(tc, "_fetch_preview_page", lambda channel, before=None: EMPTY_PAGE)
    result = tc.validate_channel("deadchannel")
    assert result["valid"] is False
    assert "no messages" in result["reason"]


def test_validate_channel_rejects_unreachable(monkeypatch):
    monkeypatch.setattr(tc, "_fetch_preview_page", lambda channel, before=None: None)
    result = tc.validate_channel("gonechannel")
    assert result["valid"] is False
    assert "unreachable" in result["reason"]


def test_validate_channel_accepts_a_real_looking_page(monkeypatch):
    monkeypatch.setattr(tc, "_fetch_preview_page", lambda channel, before=None: SAMPLE_PAGE)
    result = tc.validate_channel("getjobss")
    assert result["valid"] is True


def test_add_channel_rejects_invalid_without_storing(tmp_path, monkeypatch):
    cfg_path = tmp_path / "telegram_channels.json"
    cfg_path.write_text(json.dumps({"enabled": True, "channels": []}))
    monkeypatch.setattr(tc, "_config_path", lambda: cfg_path)
    monkeypatch.setattr(tc, "_fetch_preview_page", lambda channel, before=None: EMPTY_PAGE)

    import pytest
    with pytest.raises(ValueError):
        tc.add_channel("fakechannel")
    assert json.loads(cfg_path.read_text())["channels"] == []


def test_add_channel_persists_a_valid_one(tmp_path, monkeypatch):
    cfg_path = tmp_path / "telegram_channels.json"
    cfg_path.write_text(json.dumps({"enabled": True, "channels": []}))
    monkeypatch.setattr(tc, "_config_path", lambda: cfg_path)
    monkeypatch.setattr(tc, "_fetch_preview_page", lambda channel, before=None: SAMPLE_PAGE)

    result = tc.add_channel("getjobss")
    assert result["valid"] is True
    saved = json.loads(cfg_path.read_text())["channels"]
    assert saved[0]["username"] == "getjobss"


def test_add_channel_rejects_a_duplicate(tmp_path, monkeypatch):
    cfg_path = tmp_path / "telegram_channels.json"
    cfg_path.write_text(json.dumps({"enabled": True,
                                    "channels": [{"username": "getjobss", "name": "", "members": 0}]}))
    monkeypatch.setattr(tc, "_config_path", lambda: cfg_path)
    monkeypatch.setattr(tc, "_fetch_preview_page", lambda channel, before=None: SAMPLE_PAGE)

    import pytest
    with pytest.raises(ValueError, match="already"):
        tc.add_channel("getjobss")


def test_remove_channel(tmp_path, monkeypatch):
    cfg_path = tmp_path / "telegram_channels.json"
    cfg_path.write_text(json.dumps({"enabled": True,
                                    "channels": [{"username": "getjobss", "name": "", "members": 0}]}))
    monkeypatch.setattr(tc, "_config_path", lambda: cfg_path)

    assert tc.remove_channel("getjobss") is True
    assert json.loads(cfg_path.read_text())["channels"] == []
    assert tc.remove_channel("getjobss") is False  # already gone


def test_fetch_returns_empty_when_disabled(tmp_path, monkeypatch):
    cfg_path = tmp_path / "telegram_channels.json"
    cfg_path.write_text(json.dumps({"enabled": False, "channels": [{"username": "x"}]}))
    monkeypatch.setattr(tc, "_config_path", lambda: cfg_path)
    assert tc.fetch() == []


def test_fetch_returns_empty_with_no_channels(tmp_path, monkeypatch):
    cfg_path = tmp_path / "telegram_channels.json"
    cfg_path.write_text(json.dumps({"enabled": True, "channels": []}))
    monkeypatch.setattr(tc, "_config_path", lambda: cfg_path)
    assert tc.fetch() == []
