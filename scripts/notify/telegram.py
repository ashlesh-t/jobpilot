"""Telegram notifier — delegates to the existing scripts/telegram_notify.py.

Keeps the battle-tested Telegram HTTP wrapper as-is; this class just adapts it to the
Notifier interface so Telegram becomes one channel among several.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ for jp_secrets, telegram_notify
from .base import Notifier  # noqa: E402
from jp_secrets import get_secret_optional  # noqa: E402


class TelegramNotifier(Notifier):
    name = "telegram"
    label = "Telegram"

    def available(self) -> tuple[bool, str]:
        if not get_secret_optional("TELEGRAM_BOT_TOKEN"):
            return False, "TELEGRAM_BOT_TOKEN not set"
        if not get_secret_optional("TELEGRAM_CHAT_ID"):
            return False, "TELEGRAM_CHAT_ID not set"
        return True, ""

    def send_digest(self, text: str) -> None:
        import telegram_notify  # noqa
        telegram_notify.send_message(text)

    def send_document(self, path: Path, caption: str = "") -> None:
        import telegram_notify  # noqa
        telegram_notify.send_document(Path(path), caption)
