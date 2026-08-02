"""Applications repository — the "mark applied → …→ placed" tracker."""
from __future__ import annotations

from sqlalchemy import func, select

from ..db import session_scope
from ..models import (
    APPLICATION_PIPELINE,
    APPLICATION_TERMINAL,
    Application,
    ApplicationStatus,
    Job,
    utcnow,
)

VALID_STATUSES = [s.value for s in ApplicationStatus]
PIPELINE = [s.value for s in APPLICATION_PIPELINE]
TERMINAL = [s.value for s in APPLICATION_TERMINAL]


def _iso(dt):
    return dt.isoformat() if dt else None


def to_dict(a: Application, job: Job | None = None) -> dict:
    return {
        "id": a.id,
        "job_id": a.job_id,
        "status": a.status,
        "applied_at": _iso(a.applied_at),
        "updated_at": _iso(a.updated_at),
        "status_history": a.status_history or [],
        "notes": a.notes,
        "reminder_at": _iso(a.reminder_at),
        "days_since_update": max(0, (utcnow() - a.updated_at).days) if a.updated_at else 0,
        "company": job.company if job else "",
        "role": job.role if job else "",
        "location": job.location if job else "",
        "score": job.score if job else 0.0,
        "application_url": job.application_url if job else "",
        "source_board": job.source_board if job else "",
    }


def mark_applied(job_id: str, *, note: str = "") -> dict:
    """Idempotent: re-marking an existing application just returns it."""
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise ValueError(f"unknown job_id {job_id!r}")
        existing = s.scalar(select(Application).where(Application.job_id == job_id))
        if existing is not None:
            return to_dict(existing, job)
        now = utcnow()
        app = Application(
            job_id=job_id,
            status=ApplicationStatus.applied.value,
            applied_at=now,
            updated_at=now,
            notes=note,
            status_history=[{"status": ApplicationStatus.applied.value,
                             "at": now.isoformat(), "note": note}],
        )
        s.add(app)
        s.flush()
        return to_dict(app, job)


def unmark(job_id: str) -> bool:
    """The Undo path — removes the application entirely, restoring the job's clean state."""
    with session_scope() as s:
        app = s.scalar(select(Application).where(Application.job_id == job_id))
        if app is None:
            return False
        s.delete(app)
        return True


def set_status(job_id: str, status: str, *, note: str = "") -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {VALID_STATUSES}")
    with session_scope() as s:
        app = s.scalar(select(Application).where(Application.job_id == job_id))
        if app is None:
            raise ValueError(f"no application for job {job_id!r} — mark it applied first")
        now = utcnow()
        history = list(app.status_history or [])
        history.append({"status": status, "at": now.isoformat(), "note": note})
        app.status_history = history          # reassign so the JSON column is flagged dirty
        app.status = status
        app.updated_at = now
        if note:
            app.notes = (app.notes + "\n" if app.notes else "") + note
        job = s.get(Job, job_id)
        return to_dict(app, job)


def set_notes(job_id: str, notes: str) -> dict:
    with session_scope() as s:
        app = s.scalar(select(Application).where(Application.job_id == job_id))
        if app is None:
            raise ValueError(f"no application for job {job_id!r}")
        app.notes = notes
        job = s.get(Job, job_id)
        return to_dict(app, job)


def get(job_id: str) -> dict | None:
    with session_scope() as s:
        app = s.scalar(select(Application).where(Application.job_id == job_id))
        if app is None:
            return None
        return to_dict(app, s.get(Job, job_id))


def list_all(*, status: str | None = None, limit: int = 500) -> list[dict]:
    with session_scope() as s:
        stmt = select(Application, Job).join(Job, Job.job_id == Application.job_id)
        if status:
            stmt = stmt.where(Application.status == status)
        rows = s.execute(stmt.order_by(Application.updated_at.desc()).limit(limit)).all()
        return [to_dict(a, j) for a, j in rows]


def board() -> dict[str, list[dict]]:
    """Applications grouped by status, ready for the kanban columns."""
    grouped: dict[str, list[dict]] = {st: [] for st in VALID_STATUSES}
    for item in list_all():
        grouped.setdefault(item["status"], []).append(item)
    return grouped


def funnel() -> dict:
    """Counts per stage for the dashboard funnel chart.

    A candidate who reached `interview` has necessarily been `applied`, so the funnel is
    cumulative over the pipeline order rather than a raw group-by of current status.
    """
    with session_scope() as s:
        counts = dict(s.execute(
            select(Application.status, func.count()).group_by(Application.status)).all())
        total = s.scalar(select(func.count()).select_from(Application)) or 0

    reached: dict[str, int] = {}
    for i, stage in enumerate(PIPELINE):
        # everyone currently at this stage or any later pipeline stage
        reached[stage] = sum(counts.get(st, 0) for st in PIPELINE[i:])
    reached[PIPELINE[0]] = total  # rejected/ghosted still count as "applied"
    return {
        "total": total,
        "stages": [{"stage": st, "count": reached.get(st, 0)} for st in PIPELINE],
        "terminal": [{"stage": st, "count": counts.get(st, 0)} for st in TERMINAL],
        "in_flight": sum(counts.get(st, 0) for st in PIPELINE),
    }


def stale(days: int = 14) -> list[dict]:
    """Applications with no status change in `days` — the nudge list."""
    cutoff = utcnow().timestamp() - days * 86400
    return [
        a for a in list_all()
        if a["status"] not in TERMINAL and a["status"] != ApplicationStatus.placed.value
        and a["updated_at"] and _to_epoch(a["updated_at"]) < cutoff
    ]


def _to_epoch(iso: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return 0.0
