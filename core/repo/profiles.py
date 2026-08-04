"""Profile repository.

The DB row is authoritative, but `cache/profile.json` is written on every save because
the Layer B skills read that file directly. `profile_verified` still means exactly what
CLAUDE.md says: true only after a human confirmed the extracted profile.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ..db import session_scope
from ..models import Profile
from ..paths import ensure_user_dirs, profile_path

SKELETON: dict[str, Any] = {
    "name": "",
    "email": "",
    "phone": "",
    "skills": [],
    "experience_years": 0,
    "roles_held": [],
    "projects": [],
    "education": {},
    "publications": [],
    "graduation_date": "",
    "github_url": "",
    "portfolio_url": "",
    "linkedin_url": "",
    "interview_readiness": {
        "dsa_level": "unknown",
        "leetcode_url": "",
        "system_design": "unknown",
        "spoken_english": "unknown",
    },
    "locations": [],
    "availability": "",
    "notice_period_days": 0,
}


def _iso(dt):
    return dt.isoformat() if dt else None


def to_dict(p: Profile) -> dict:
    data = dict(SKELETON)
    data.update(p.data or {})
    data["profile_verified"] = p.verified
    data["hash"] = p.resume_hash
    data["_id"] = p.id
    data["_resume_id"] = p.resume_id
    data["_updated_at"] = _iso(p.updated_at)
    return data


def current(user_id: int) -> dict | None:
    with session_scope() as s:
        p = s.scalar(select(Profile).where(Profile.user_id == user_id, Profile.is_active.is_(True))
                     .order_by(Profile.updated_at.desc()))
        return to_dict(p) if p else None


def get_or_empty(user_id: int) -> dict:
    return current(user_id) or {**SKELETON, "profile_verified": False, "hash": ""}


def save(user_id: int, data: dict, *, verified: bool | None = None, resume_id: int | None = None,
         resume_hash: str | None = None) -> dict:
    """Merge-write the active profile (creating it if absent) and export profile.json."""
    payload = {k: v for k, v in data.items() if not k.startswith("_")}
    payload.pop("profile_verified", None)
    payload.pop("hash", None)

    with session_scope() as s:
        p = s.scalar(select(Profile).where(Profile.user_id == user_id, Profile.is_active.is_(True))
                     .order_by(Profile.updated_at.desc()))
        if p is None:
            p = Profile(user_id=user_id, data={}, is_active=True)
            s.add(p)
        merged = dict(p.data or {})
        merged.update(payload)
        p.data = merged                     # reassign so the JSON column is flagged dirty
        if resume_id is not None:
            p.resume_id = resume_id
        if resume_hash is not None:
            # A new resume invalidates human verification (CLAUDE.md profile_verified rule).
            if resume_hash != p.resume_hash:
                p.verified = False
            p.resume_hash = resume_hash
        if verified is not None:
            p.verified = verified
        s.flush()
        out = to_dict(p)

    export(user_id, out)
    return out


def set_verified(user_id: int, value: bool) -> dict:
    return save(user_id, {}, verified=value)


def export(user_id: int, data: dict | None = None) -> None:
    """Write cache/profile.json for the Layer B skills (read-before-write)."""
    payload = data or {}
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    ensure_user_dirs(user_id)
    path = profile_path(user_id)
    current_file: dict = {}
    if path.exists():
        try:
            current_file = json.loads(path.read_text())
        except Exception:
            current_file = {}
    current_file.update(payload)
    path.write_text(json.dumps(current_file, indent=2, ensure_ascii=False))


def is_verified(user_id: int) -> bool:
    p = current(user_id)
    return bool(p and p.get("profile_verified"))
