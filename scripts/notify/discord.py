"""Discord notifier — posts to a webhook URL.

A Discord webhook is the whole credential: no bot, no OAuth, no gateway. The user pastes
a channel webhook URL in the UI; we store it as the DISCORD_WEBHOOK_URL secret.
Digest text posts as message content; documents post as multipart attachments.
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ for jp_secrets
from .base import Notifier  # noqa: E402
from jp_secrets import get_secret_optional  # noqa: E402

# Discord hard-caps message content at 2000 chars.
_MAX_CONTENT = 1990


class DiscordNotifier(Notifier):
    name = "discord"
    label = "Discord"

    def _webhook(self) -> str | None:
        return get_secret_optional("DISCORD_WEBHOOK_URL")

    def available(self) -> tuple[bool, str]:
        url = self._webhook()
        if not url:
            return False, "DISCORD_WEBHOOK_URL not set"
        if "discord.com/api/webhooks/" not in url and "discordapp.com/api/webhooks/" not in url:
            return False, "DISCORD_WEBHOOK_URL is not a valid Discord webhook URL"
        return True, ""

    def send_digest(self, text: str) -> None:
        url = self._webhook()
        if not url:
            raise RuntimeError("DISCORD_WEBHOOK_URL not set")
        # Discord rejects >2000 char content; wrap in a code block and chunk.
        for chunk in _chunks(text, _MAX_CONTENT):
            resp = requests.post(url, json={"content": chunk}, timeout=30)
            resp.raise_for_status()

    def send_document(self, path: Path, caption: str = "") -> None:
        url = self._webhook()
        if not url:
            raise RuntimeError("DISCORD_WEBHOOK_URL not set")
        path = Path(path)
        with path.open("rb") as fh:
            data = {"content": caption[:_MAX_CONTENT]} if caption else {}
            resp = requests.post(
                url, data=data,
                files={"file": (path.name, fh)},
                timeout=60,
            )
            resp.raise_for_status()


def _chunks(text: str, size: int):
    text = text or ""
    if len(text) <= size:
        yield text
        return
    # Prefer splitting on line boundaries to keep the digest readable.
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > size:
            if buf:
                yield buf
            buf = line
        else:
            buf += line
    if buf:
        yield buf
