"""Central secret loader for JobPilot.

Priority order:
  1. OS keyring (via the `keyring` library, service name "jobpilot")
  2. .env file (via python-dotenv) — first the data-dir .env, then a repo-local .env

Every other script imports `get_secret` from here. Scripts must NEVER read env vars directly.
"""
from __future__ import annotations

import os
from pathlib import Path

KEYRING_SERVICE = "jobpilot"


def _jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _load_dotenv_files() -> None:
    """Load .env files into os.environ (without overriding already-set vars)."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    candidates = [
        _jobpilot_dir() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for path in candidates:
        if path.is_file():
            load_dotenv(dotenv_path=str(path), override=False)


_load_dotenv_files()


def get_secret(key: str) -> str:
    """Return a secret by name, raising KeyError if it cannot be found.

    Tries the OS keyring first, then environment variables (populated from .env).
    """
    # 1) OS keyring
    try:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, key)
        if value:
            return value
    except Exception:
        pass

    # 2) environment / .env
    value = os.environ.get(key)
    if value:
        return value

    raise KeyError(
        f"Secret '{key}' not found. Set it via your OS keyring "
        f"(service '{KEYRING_SERVICE}') or in {_jobpilot_dir() / '.env'}."
    )


def get_secret_optional(key: str, default: str | None = None) -> str | None:
    """Like get_secret but returns `default` instead of raising."""
    try:
        return get_secret(key)
    except KeyError:
        return default


if __name__ == "__main__":
    import sys

    keys = sys.argv[1:] or ["APIFY_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    for k in keys:
        present = get_secret_optional(k) is not None
        print(f"{k}: {'FOUND' if present else 'MISSING'}")
