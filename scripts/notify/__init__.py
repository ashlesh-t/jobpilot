"""Notifier package — pluggable digest/document delivery (OCP).

Adding a channel = drop one module implementing Notifier and register it here. The
pipeline and service call `fan_out(...)`; they never import a concrete channel.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ for jp_secrets, telegram_notify
from .base import Notifier  # noqa: E402
from .telegram import TelegramNotifier  # noqa: E402
from .discord import DiscordNotifier  # noqa: E402

_REGISTRY = {
    TelegramNotifier.name: TelegramNotifier,
    DiscordNotifier.name: DiscordNotifier,
}


def get_notifier(name: str) -> Notifier:
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        raise ValueError(f"unknown notifier '{name}'. Options: {sorted(_REGISTRY)}")
    return cls()


def list_notifiers() -> list[dict]:
    out = []
    for name, cls in _REGISTRY.items():
        n = cls()
        ok, reason = n.available()
        out.append({"name": name, "label": n.label, "available": ok, "reason": reason})
    return out


def enabled_notifiers(channels: list[str]) -> list[Notifier]:
    """Instantiate the configured channels that are actually available."""
    result = []
    for name in channels or []:
        try:
            n = get_notifier(name)
        except ValueError:
            continue
        if n.available()[0]:
            result.append(n)
    return result


def fan_out(channels: list[str], *, digest: str | None = None,
            documents: list[tuple] | None = None) -> dict:
    """Send digest + documents to every enabled channel. Returns {channel: ok|error}.

    documents: list of (path, caption) tuples.
    """
    results: dict[str, str] = {}
    for n in enabled_notifiers(channels):
        try:
            if digest:
                n.send_digest(digest)
            for path, caption in (documents or []):
                n.send_document(Path(path), caption)
            results[n.name] = "ok"
        except Exception as exc:  # noqa: BLE001
            results[n.name] = f"error: {exc}"
    return results


__all__ = ["Notifier", "get_notifier", "list_notifiers", "enabled_notifiers", "fan_out"]
