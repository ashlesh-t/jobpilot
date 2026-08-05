"""Thin wrapper over `scripts/scrapers/telegram_channels.py` — the one path to the
Telegram channel list.

This is file-backed (config/telegram_channels.json), not a database table — it
configures a scraper, the same tier as config/target_companies.json, not user data.
Every write goes through validate_channel() first, so a bad channel is rejected
synchronously and never silently stored — mirrors core/secrets.py's relationship to
scripts/jp_secrets.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_DIR / "scripts"
SCRAPERS_DIR = SCRIPTS_DIR / "scrapers"
for p in (SCRIPTS_DIR, SCRAPERS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import telegram_channels as _tg  # noqa: E402


def list_channels() -> list[dict]:
    return _tg.list_channels()


def add_channel(username: str) -> dict:
    """Validates live before storing. Raises ValueError if the channel isn't real."""
    return _tg.add_channel(username)


def remove_channel(username: str) -> bool:
    return _tg.remove_channel(username)


def revalidate_all() -> list[dict]:
    return _tg.revalidate_all()
