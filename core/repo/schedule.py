"""Schedule-slot repository.

APScheduler's own jobstore holds the *timers*; these rows hold the user's *intent* plus
the last-fire bookkeeping that makes catch-up decidable after the daemon was down.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select

from ..db import session_scope
from ..models import ScheduleSlot, utcnow

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DEFAULT_TZ = "Asia/Kolkata"


def validate_time(hhmm: str) -> str:
    if not TIME_RE.match(hhmm or ""):
        raise ValueError(f"invalid time {hhmm!r} — expected 24-hour HH:MM, e.g. 09:30")
    return hhmm


def _iso(dt):
    return dt.isoformat() if dt else None


def to_dict(s: ScheduleSlot) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "time": s.time_hhmm,
        "timezone": s.timezone,
        "mode": s.mode,
        "enabled": s.enabled,
        "days": s.days,
        "last_fired_at": _iso(s.last_fired_at),
        "last_run_id": s.last_run_id,
        "last_outcome": s.last_outcome,
        "job_id": f"slot-{s.id}",
    }


def _unique_name(session, user_id: int, base: str) -> str:
    name = base or "slot"
    n = 1
    while session.scalar(select(ScheduleSlot).where(
            ScheduleSlot.user_id == user_id, ScheduleSlot.name == name)) is not None:
        n += 1
        name = f"{base}-{n}"
    return name


def create(user_id: int, *, name: str, time: str, timezone: str = DEFAULT_TZ, mode: str = "auto",
           days: str = "*", enabled: bool = True) -> dict:
    validate_time(time)
    with session_scope() as s:
        row = ScheduleSlot(user_id=user_id, name=_unique_name(s, user_id, name.strip() or "slot"),
                           time_hhmm=time, timezone=timezone, mode=mode, days=days, enabled=enabled)
        s.add(row)
        s.flush()
        return to_dict(row)


def update(user_id: int, slot_id: int, **fields) -> dict | None:
    if "time" in fields:
        validate_time(fields["time"])
    with session_scope() as s:
        row = s.get(ScheduleSlot, slot_id)
        if row is None or row.user_id != user_id:
            return None
        mapping = {"time": "time_hhmm", "name": "name", "timezone": "timezone",
                   "mode": "mode", "days": "days", "enabled": "enabled"}
        for key, attr in mapping.items():
            if key in fields and fields[key] is not None:
                setattr(row, attr, fields[key])
        s.flush()
        return to_dict(row)


def delete(user_id: int, slot_id: int) -> bool:
    with session_scope() as s:
        row = s.get(ScheduleSlot, slot_id)
        if row is None or row.user_id != user_id:
            return False
        s.delete(row)
        return True


def get(user_id: int, slot_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(ScheduleSlot, slot_id)
        if row is None or row.user_id != user_id:
            return None
        return to_dict(row)


def list_all(user_id: int, *, enabled_only: bool = False) -> list[dict]:
    with session_scope() as s:
        stmt = select(ScheduleSlot).where(ScheduleSlot.user_id == user_id).order_by(ScheduleSlot.time_hhmm)
        if enabled_only:
            stmt = stmt.where(ScheduleSlot.enabled.is_(True))
        return [to_dict(r) for r in s.scalars(stmt).all()]


def record_fire(user_id: int, slot_id: int, *, run_id: str = "", outcome: str = "started",
                when: datetime | None = None) -> None:
    """Stamp a fire. Catch-up passes `when` = the occurrence it served, not wall-clock,
    so the same missed slot is never picked up twice."""
    with session_scope() as s:
        row = s.get(ScheduleSlot, slot_id)
        if row is None or row.user_id != user_id:
            return
        row.last_fired_at = when or utcnow()
        row.last_run_id = run_id or row.last_run_id
        row.last_outcome = outcome


def set_outcome(user_id: int, slot_id: int, outcome: str) -> None:
    with session_scope() as s:
        row = s.get(ScheduleSlot, slot_id)
        if row is not None and row.user_id == user_id:
            row.last_outcome = outcome


def list_all_enabled_across_users() -> list[dict]:
    """Every enabled slot on the instance, across every account — what the scheduler's
    APScheduler timers are rebuilt from at startup and on every `reconfigure()`.

    Each dict is `to_dict()` plus `user_id`, since the scheduler needs to know which
    account's run to fire when the timer goes off."""
    with session_scope() as s:
        rows = s.scalars(
            select(ScheduleSlot).where(ScheduleSlot.enabled.is_(True))
            .order_by(ScheduleSlot.time_hhmm)).all()
        return [{**to_dict(r), "user_id": r.user_id} for r in rows]


def missed_since_downtime(user_id: int, grace_hours: int = 6, now: datetime | None = None) -> list[dict]:
    """Enabled slots whose most recent fire time passed unserved within the grace window.

    "Unserved" means the slot has no `last_fired_at` at or after that occurrence. At most
    one catch-up per slot is ever returned, so a laptop closed for a week produces one run,
    not seven.
    """
    from zoneinfo import ZoneInfo

    now = now or utcnow()
    due: list[dict] = []
    for slot in list_all(user_id, enabled_only=True):
        try:
            tz = ZoneInfo(slot["timezone"] or DEFAULT_TZ)
        except Exception:
            tz = ZoneInfo(DEFAULT_TZ)
        local_now = now.astimezone(tz)
        hh, mm = (int(x) for x in slot["time"].split(":"))
        occurrence = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if occurrence > local_now:
            occurrence -= timedelta(days=1)     # today's slot hasn't come around yet
        if (local_now - occurrence) > timedelta(hours=grace_hours):
            continue                            # too old to be worth a surprise run
        last = slot["last_fired_at"]
        if last:
            try:
                if datetime.fromisoformat(last).astimezone(tz) >= occurrence:
                    continue                    # already served this occurrence
            except ValueError:
                pass
        due.append({**slot, "occurrence": occurrence.isoformat()})
    return due
