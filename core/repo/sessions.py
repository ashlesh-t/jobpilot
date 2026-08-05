"""Session repository — the server-side half of the login cookie."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from ..auth import new_session_expiry, new_session_token
from ..db import session_scope
from ..models import Session as SessionRow
from ..models import User


def create(user_id: int, *, user_agent: str = "", ip: str = "") -> str:
    token = new_session_token()
    with session_scope() as s:
        s.add(SessionRow(id=token, user_id=user_id, expires_at=new_session_expiry(),
                         user_agent=user_agent[:255], ip=ip[:64]))
    return token


def get_user(token: str) -> dict | None:
    """Resolve a session token to its user, or None if missing/expired."""
    if not token:
        return None
    with session_scope() as s:
        row = s.get(SessionRow, token)
        if row is None:
            return None
        if row.expires_at < datetime.now(timezone.utc):
            s.delete(row)
            return None
        user = s.get(User, row.user_id)
        if user is None:
            s.delete(row)
            return None
        return {
            "id": user.id, "username": user.username, "email": user.email,
            "is_admin": user.is_admin, "must_set_password": user.must_set_password,
        }


def revoke(token: str) -> None:
    with session_scope() as s:
        s.execute(delete(SessionRow).where(SessionRow.id == token))


def revoke_all(user_id: int) -> None:
    with session_scope() as s:
        s.execute(delete(SessionRow).where(SessionRow.user_id == user_id))


def purge_expired() -> int:
    with session_scope() as s:
        rows = s.scalars(select(SessionRow).where(SessionRow.expires_at < datetime.now(timezone.utc))).all()
        for row in rows:
            s.delete(row)
        return len(rows)
