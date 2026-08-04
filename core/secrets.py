"""Per-user secrets — the one path to credentials.

Every secret (Apify token, Telegram bot token, Anthropic key, ...) is stored encrypted
in the `user_secrets` table, scoped to whichever account it belongs to (see
core/crypto.py for the encryption key and core/repo/user_secrets.py for persistence).
Nothing here is written to the OS keyring or `.env` any more — that path only remains
for the pre-auth CLI bootstrap wizard and for standalone Layer A subprocesses, both of
which go through scripts/jp_secrets.py instead (it falls back to this module when a
`JOBPILOT_USER_ID` is set in its environment).

Secrets are never returned by an API response unless the caller explicitly asks to
reveal one.
"""
from __future__ import annotations

from .repo import user_secrets as _repo

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


def get(user_id: int, key: str) -> str | None:
    return _repo.get(user_id, key)


def require(user_id: int, key: str) -> str:
    value = get(user_id, key)
    if not value:
        raise KeyError(f"Secret '{key}' is not set for user {user_id}.")
    return value


def set(user_id: int, key: str, value: str) -> None:  # noqa: A001
    _repo.set(user_id, key, (value or "").strip())


def has(user_id: int, key: str) -> bool:
    return bool(get(user_id, key))


def mask(value: str | None) -> str:
    """`sk-ant-api03-abcdef…9f2a` → `sk-ant-…9f2a`. Never reveals the middle."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:6]}…{value[-4:]}"


def status(user_id: int, keys: list[str] | None = None) -> list[dict]:
    """Presence + masked preview for every known secret. Never returns a raw value."""
    wanted = {k: True for k in (keys or KNOWN_KEYS)}
    out = []
    for spec in KNOWN_SECRETS:
        if spec["key"] not in wanted:
            continue
        value = get(user_id, spec["key"])
        out.append({**spec, "set": bool(value), "masked": mask(value)})
    return out


def reveal(user_id: int, key: str) -> str | None:
    """The single explicit path to a plaintext value — used only by the vault's
    reveal button, which the UI guards behind a confirmation."""
    return get(user_id, key)
