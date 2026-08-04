"""Thin wrapper over `scripts/jp_secrets.py` — the one path to credentials.

Secrets live in the OS keyring, falling back to `<jobpilot_dir>/.env`. They are never
written to the database and never returned by an API response unless the caller
explicitly asks to reveal one. Everything in core/, server/ and orchestrator/ imports
from here so the import-path fixups live in exactly one place.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import jp_secrets  # noqa: E402

# Everything JobPilot may hold, with the label and help text the UI renders.
KNOWN_SECRETS: list[dict] = [
    {"key": "ANTHROPIC_API_KEY", "label": "Anthropic API key", "group": "engine",
     "help": "Enables the metered Claude API backend and the per-run cost meter. "
             "Not needed if you use a Claude Pro/Max subscription."},
    {"key": "APIFY_TOKEN", "label": "Apify token", "group": "scraping",
     "help": "Unlocks LinkedIn, Naukri, Glassdoor and other blocked sources. "
             "Optional — the free native scrapers work without it."},
    {"key": "APIFY_TOKEN_2", "label": "Apify token (slot 2)", "group": "scraping",
     "help": "A second Apify account, used automatically when slot 1 runs out of credit."},
    {"key": "APIFY_TOKEN_3", "label": "Apify token (slot 3)", "group": "scraping",
     "help": "A third Apify account for the same rotation."},
    {"key": "TELEGRAM_BOT_TOKEN", "label": "Telegram bot token", "group": "notify",
     "help": "From @BotFather, after /newbot. Paste the whole token — digits, colon and "
             "letters together, like 123456789:AAH… — not just the numbers, and none of "
             "the words around it. Used to send your digest, report and tailored resumes."},
    {"key": "TELEGRAM_CHAT_ID", "label": "Telegram chat ID", "group": "notify",
     "help": "Which chat the bot messages. Captured automatically when you message the bot."},
    {"key": "DISCORD_WEBHOOK_URL", "label": "Discord webhook", "group": "notify",
     "help": "Optional second delivery channel. Create one in Channel Settings → Integrations."},
    {"key": "GEMINI_API_KEY", "label": "Gemini API key", "group": "engine",
     "help": "For the Google Gemini backend."},
    {"key": "ADZUNA_APP_ID", "label": "Adzuna app ID", "group": "scraping",
     "help": "Adds the Adzuna job board as a free native source. Get one at "
             "developer.adzuna.com/signup — no card needed, 1,000 calls/month on the "
             "free tier. After registering, your App ID and App Key are both on the "
             "dashboard at developer.adzuna.com/admin/. Optional — the free scrapers "
             "work without it."},
    {"key": "ADZUNA_APP_KEY", "label": "Adzuna app key", "group": "scraping",
     "help": "Pairs with the Adzuna app ID — copy both from the same "
             "developer.adzuna.com/admin/ dashboard page."},
]

KNOWN_KEYS = [s["key"] for s in KNOWN_SECRETS]


def get(key: str) -> str | None:
    return jp_secrets.get_secret_optional(key)


def require(key: str) -> str:
    return jp_secrets.get_secret(key)


def set(key: str, value: str) -> str:  # noqa: A001
    """Store a secret. Returns the backend that took it: 'keyring' or 'env'."""
    return jp_secrets.set_secret(key, value)


def has(key: str) -> bool:
    return bool(get(key))


def mask(value: str | None) -> str:
    """`sk-ant-api03-abcdef…9f2a` → `sk-ant-…9f2a`. Never reveals the middle."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:6]}…{value[-4:]}"


def status(keys: list[str] | None = None) -> list[dict]:
    """Presence + masked preview for every known secret. Never returns a raw value."""
    wanted = {k: True for k in (keys or KNOWN_KEYS)}
    out = []
    for spec in KNOWN_SECRETS:
        if spec["key"] not in wanted:
            continue
        value = get(spec["key"])
        out.append({**spec, "set": bool(value), "masked": mask(value)})
    return out


def reveal(key: str) -> str | None:
    """The single explicit path to a plaintext value — used only by the vault's
    reveal button, which the UI guards behind a confirmation."""
    return get(key)
