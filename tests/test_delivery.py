"""Delivery fan-out — the fix that makes Discord (and any extra channel) take effect
on real runs, not just the UI test button."""
import json

import notify
import telegram_notify


def test_fan_out_excludes_telegram_and_forwards_digest(tmp_path, monkeypatch):
    (tmp_path / "options").mkdir(parents=True)
    (tmp_path / "options" / "preferences.json").write_text(
        json.dumps({"notify_channels": ["telegram", "discord"]}))
    monkeypatch.setattr(telegram_notify, "jobpilot_dir", lambda: tmp_path)

    captured = {}

    def fake_fan_out(channels, digest=None, documents=None):
        captured.update(channels=channels, digest=digest, documents=documents)
        return {c: "ok" for c in channels}

    monkeypatch.setattr(notify, "fan_out", fake_fan_out)

    telegram_notify.fan_out_extra_channels("hello digest", None)

    # Telegram is handled by the script itself and must be excluded from the fan-out
    assert captured["channels"] == ["discord"]
    assert captured["digest"] == "hello digest"


def test_fan_out_noop_when_only_telegram(tmp_path, monkeypatch):
    (tmp_path / "options").mkdir(parents=True)
    (tmp_path / "options" / "preferences.json").write_text(
        json.dumps({"notify_channels": ["telegram"]}))
    monkeypatch.setattr(telegram_notify, "jobpilot_dir", lambda: tmp_path)

    called = {"hit": False}
    monkeypatch.setattr(notify, "fan_out",
                        lambda *a, **k: called.__setitem__("hit", True))

    telegram_notify.fan_out_extra_channels("d", None)
    assert called["hit"] is False


def test_fan_out_survives_missing_prefs(tmp_path, monkeypatch):
    # no preferences.json → silent no-op, never raises
    monkeypatch.setattr(telegram_notify, "jobpilot_dir", lambda: tmp_path)
    telegram_notify.fan_out_extra_channels("d", None)
