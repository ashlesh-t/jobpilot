"""Password hashing and session tokens. Pure functions only — no DB session handling
here, so this module is safe to import from a migration as well as from server code.
See core/repo/users.py and core/repo/sessions.py for the persistence side.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

SESSION_TTL = timedelta(days=30)
SESSION_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def new_session_expiry() -> datetime:
    return datetime.now(timezone.utc) + SESSION_TTL


def locked_password_hash() -> str:
    """A password hash nobody can satisfy — used for the auto-created legacy account
    from an existing single-user install (see migration 0004). Bcrypt-verified against
    a random, never-stored password, so it always fails until reset via /api/auth/claim
    or `jobpilot setup`."""
    return hash_password(secrets.token_urlsafe(32))
