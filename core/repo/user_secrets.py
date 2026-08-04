"""Per-user encrypted secrets repository. Values are Fernet-encrypted (core/crypto.py)
before they ever reach a row — see core/secrets.py for the public API everything else
should use instead of importing this module directly."""
from __future__ import annotations

from sqlalchemy import select

from .. import crypto
from ..db import session_scope
from ..models import UserSecret


def get(user_id: int, key: str) -> str | None:
    with session_scope() as s:
        row = s.get(UserSecret, (user_id, key))
        if row is None:
            return None
        try:
            return crypto.decrypt(row.value_encrypted)
        except Exception:
            return None


def set(user_id: int, key: str, value: str) -> None:  # noqa: A001
    encrypted = crypto.encrypt(value)
    with session_scope() as s:
        row = s.get(UserSecret, (user_id, key))
        if row is None:
            s.add(UserSecret(user_id=user_id, key=key, value_encrypted=encrypted))
        else:
            row.value_encrypted = encrypted


def delete(user_id: int, key: str) -> None:
    with session_scope() as s:
        row = s.get(UserSecret, (user_id, key))
        if row is not None:
            s.delete(row)


def keys_set(user_id: int) -> set[str]:
    with session_scope() as s:
        rows = s.scalars(select(UserSecret.key).where(UserSecret.user_id == user_id)).all()
        return set(rows)
