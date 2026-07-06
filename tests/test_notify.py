"""Notifier unit tests — availability + Discord chunking, no network."""
import notify
from notify.discord import _chunks, DiscordNotifier


def test_registry_lists_channels():
    names = {n["name"] for n in notify.list_notifiers()}
    assert {"telegram", "discord"} <= names


def test_discord_unavailable_without_webhook(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    ok, reason = DiscordNotifier().available()
    assert ok is False and "DISCORD_WEBHOOK_URL" in reason


def test_discord_rejects_non_webhook(monkeypatch):
    # discord.py binds get_secret_optional at import — patch it on that module.
    import notify.discord as disc
    monkeypatch.setattr(disc, "get_secret_optional",
                        lambda k, d=None: "https://example.com/not-a-webhook")
    ok, reason = DiscordNotifier().available()
    assert ok is False and "valid Discord webhook" in reason


def test_chunks_respects_limit():
    text = "\n".join(f"line {i} " + "x" * 60 for i in range(200))
    parts = list(_chunks(text, 1990))
    assert len(parts) > 1
    assert all(len(p) <= 1990 for p in parts)
    assert "".join(parts) == text


def test_enabled_notifiers_filters_unavailable(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify.enabled_notifiers(["telegram", "discord"]) == []
    assert notify.fan_out(["telegram", "discord"], digest="hi") == {}
