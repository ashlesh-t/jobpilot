"""Referrals repository — drafted referral-request messages, one per (job, contact).

Draft-only: nothing here ever sends anything. `create()` persists whatever message
text the caller already generated (see server/routes_referrals.py); `set_status`
tracks what the user did with it afterward (sent it themselves, got a response, etc).
"""
from __future__ import annotations

from sqlalchemy import select

from ..db import session_scope
from ..models import Contact, Job, Referral, ReferralStatus, utcnow

VALID_STATUSES = [s.value for s in ReferralStatus]


def _iso(dt):
    return dt.isoformat() if dt else None


def to_dict(r: Referral, job: Job | None = None, contact: Contact | None = None) -> dict:
    return {
        "id": r.id,
        "job_id": r.job_id,
        "contact_id": r.contact_id,
        "message": r.message,
        "status": r.status,
        "status_history": r.status_history or [],
        "engine": r.engine,
        "cost_usd": round(r.cost_usd, 4),
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
        "company": job.company if job else "",
        "role": job.role if job else "",
        "contact_name": contact.name if contact else "",
        "contact_email": contact.email if contact else "",
    }


def create(user_id: int, job_id: str, contact_id: int, *, message: str, engine: str = "",
          cost_usd: float = 0.0) -> dict:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise ValueError(f"unknown job_id {job_id!r}")
        contact = s.get(Contact, contact_id)
        if contact is None or contact.user_id != user_id:
            raise ValueError(f"unknown contact_id {contact_id!r}")
        now = utcnow()
        row = Referral(
            user_id=user_id, job_id=job_id, contact_id=contact_id, message=message,
            status=ReferralStatus.drafted.value, engine=engine, cost_usd=cost_usd,
            created_at=now, updated_at=now,
            status_history=[{"status": ReferralStatus.drafted.value,
                             "at": now.isoformat(), "note": ""}],
        )
        s.add(row)
        s.flush()
        return to_dict(row, job, contact)


def set_status(user_id: int, referral_id: int, status: str, *, note: str = "") -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {VALID_STATUSES}")
    with session_scope() as s:
        row = s.get(Referral, referral_id)
        if row is None or row.user_id != user_id:
            raise ValueError(f"no referral {referral_id!r}")
        now = utcnow()
        history = list(row.status_history or [])
        history.append({"status": status, "at": now.isoformat(), "note": note})
        row.status_history = history  # reassign so the JSON column is flagged dirty
        row.status = status
        row.updated_at = now
        job = s.get(Job, row.job_id)
        contact = s.get(Contact, row.contact_id)
        return to_dict(row, job, contact)


def get(user_id: int, referral_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(Referral, referral_id)
        if row is None or row.user_id != user_id:
            return None
        return to_dict(row, s.get(Job, row.job_id), s.get(Contact, row.contact_id))


def for_job(user_id: int, job_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(Referral).where(
            Referral.user_id == user_id, Referral.job_id == job_id)
            .order_by(Referral.created_at.desc())).all()
        job = s.get(Job, job_id)
        return [to_dict(r, job, s.get(Contact, r.contact_id)) for r in rows]


def list_all(user_id: int, *, status: str | None = None, limit: int = 500) -> list[dict]:
    with session_scope() as s:
        stmt = select(Referral).where(Referral.user_id == user_id)
        if status:
            stmt = stmt.where(Referral.status == status)
        rows = s.scalars(stmt.order_by(Referral.created_at.desc()).limit(limit)).all()
        return [to_dict(r, s.get(Job, r.job_id), s.get(Contact, r.contact_id)) for r in rows]


def remove(user_id: int, referral_id: int) -> bool:
    with session_scope() as s:
        row = s.get(Referral, referral_id)
        if row is None or row.user_id != user_id:
            return False
        s.delete(row)
        return True
