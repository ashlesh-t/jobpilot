"""Accounts repository — one row per person on this JobPilot instance."""
from __future__ import annotations

from sqlalchemy import func, select

from ..auth import hash_password, verify_password
from ..db import session_scope
from ..models import User


def to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "is_admin": u.is_admin,
        "must_set_password": u.must_set_password,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def create(*, username: str, password: str, email: str | None = None,
          is_admin: bool = False) -> dict:
    with session_scope() as s:
        row = User(username=username.strip(), email=(email or "").strip() or None,
                   password_hash=hash_password(password), is_admin=is_admin)
        s.add(row)
        s.flush()
        return to_dict(row)


def get_by_id(user_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(User, user_id)
        return to_dict(row) if row else None


def get_by_username(username: str) -> dict | None:
    with session_scope() as s:
        row = s.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
        return to_dict(row) if row else None


def authenticate(username: str, password: str) -> dict | None:
    """Verify credentials and return the user dict, or None on any mismatch."""
    with session_scope() as s:
        row = s.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
        if row is None or not verify_password(password, row.password_hash):
            return None
        return to_dict(row)


def count() -> int:
    with session_scope() as s:
        return s.scalar(select(func.count()).select_from(User)) or 0


def set_password(user_id: int, password: str) -> dict | None:
    with session_scope() as s:
        row = s.get(User, user_id)
        if row is None:
            return None
        row.password_hash = hash_password(password)
        row.must_set_password = False
        s.flush()
        return to_dict(row)


def claim_legacy(user_id: int, *, username: str, password: str) -> dict | None:
    """Rename the auto-created legacy account and give it a real password — the flow
    `jobpilot setup` drives after an upgrade backfills a locked admin row."""
    with session_scope() as s:
        row = s.get(User, user_id)
        if row is None or not row.must_set_password:
            return None
        row.username = username.strip()
        row.password_hash = hash_password(password)
        row.must_set_password = False
        s.flush()
        return to_dict(row)


def touch_last_login(user_id: int) -> None:
    from datetime import datetime, timezone

    with session_scope() as s:
        row = s.get(User, user_id)
        if row is not None:
            row.last_login_at = datetime.now(timezone.utc)


def find_legacy() -> dict | None:
    """The single auto-created legacy account from an upgrade backfill, if unclaimed."""
    with session_scope() as s:
        row = s.scalar(select(User).where(User.must_set_password.is_(True)))
        return to_dict(row) if row else None
