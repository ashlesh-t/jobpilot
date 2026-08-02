"""Runs / phases / events repository — the durable backing for the live run view."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from ..db import session_scope
from ..models import Phase, PhaseStatus, Run, RunEvent, RunStatus, Scan, utcnow


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def new_run_id() -> str:
    """Second-granularity UTC stamp, uniquified if a run already exists in that second."""
    base = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    with session_scope() as s:
        if s.get(Run, base) is None:
            return base
        n = 2
        while s.get(Run, f"{base}-{n}") is not None:
            n += 1
        return f"{base}-{n}"


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def create(run_id: str, *, mode: str, engine: str, phase_keys: list[str],
           trigger: str = "manual", slot_name: str = "") -> dict:
    with session_scope() as s:
        run = Run(id=run_id, mode=mode, engine=engine, trigger=trigger,
                  slot_name=slot_name, status=RunStatus.pending.value)
        s.add(run)
        for i, key in enumerate(phase_keys):
            s.add(Phase(run_id=run_id, phase_key=key, position=i,
                        status=PhaseStatus.pending.value))
        s.add(Scan(run_id=run_id, mode=mode, engine=engine))
        s.flush()
        return to_dict(run)


def set_status(run_id: str, status: str, *, error: str = "", summary: str | None = None,
               ended: bool = False) -> None:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        run.status = status
        if error:
            run.error = error
        if summary is not None:
            run.summary = summary[:4000]
        if ended:
            run.ended_at = utcnow()


def to_dict(run: Run, *, with_phases: bool = True) -> dict:
    d = {
        "id": run.id,
        "status": run.status,
        "mode": run.mode,
        "engine": run.engine,
        "trigger": run.trigger,
        "slot_name": run.slot_name,
        "started_at": _iso(run.started_at),
        "ended_at": _iso(run.ended_at),
        "error": run.error,
        "summary": run.summary,
        "cost_usd": round(run.cost_usd, 4),
        "tokens_in": run.tokens_in,
        "tokens_out": run.tokens_out,
    }
    if with_phases:
        d["phases"] = [phase_to_dict(p) for p in sorted(run.phases, key=lambda p: p.position)]
    return d


def get(run_id: str) -> dict | None:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            return None
        d = to_dict(run)
        scan = s.scalar(select(Scan).where(Scan.run_id == run_id))
        d["scan"] = scan_to_dict(scan) if scan else None
        return d


def active() -> dict | None:
    with session_scope() as s:
        run = s.scalar(
            select(Run)
            .where(Run.status.in_([RunStatus.pending.value, RunStatus.running.value,
                                   RunStatus.waiting_network.value]))
            .order_by(Run.started_at.desc()))
        return to_dict(run) if run else None


def history(limit: int = 50, offset: int = 0) -> list[dict]:
    with session_scope() as s:
        runs = s.scalars(
            select(Run).order_by(Run.started_at.desc()).offset(offset).limit(limit)).all()
        return [to_dict(r) for r in runs]


def reset_orphans() -> int:
    """Mark runs left 'running' by a crash or restart as errored. Called at startup."""
    with session_scope() as s:
        stuck = s.scalars(select(Run).where(
            Run.status.in_([RunStatus.running.value, RunStatus.pending.value]))).all()
        for run in stuck:
            run.status = RunStatus.error.value
            run.error = run.error or "interrupted — the service stopped while this run was active"
            run.ended_at = run.ended_at or utcnow()
            for p in run.phases:
                if p.status in (PhaseStatus.running.value, PhaseStatus.pending.value):
                    p.status = PhaseStatus.cancelled.value
        return len(stuck)


# --------------------------------------------------------------------------- #
# Phases
# --------------------------------------------------------------------------- #
def phase_to_dict(p: Phase) -> dict:
    return {
        "key": p.phase_key,
        "position": p.position,
        "status": p.status,
        "attempt": p.attempt,
        "started_at": _iso(p.started_at),
        "ended_at": _iso(p.ended_at),
        "error": p.error,
        "artifact": p.artifact or {},
        "cost_usd": round(p.cost_usd, 4),
        "tokens_in": p.tokens_in,
        "tokens_out": p.tokens_out,
        "duration_s": (
            round((p.ended_at - p.started_at).total_seconds(), 1)
            if p.started_at and p.ended_at else None
        ),
    }


def get_phase(run_id: str, phase_key: str) -> dict | None:
    with session_scope() as s:
        p = s.scalar(select(Phase).where(Phase.run_id == run_id, Phase.phase_key == phase_key))
        return phase_to_dict(p) if p else None


def phase_start(run_id: str, phase_key: str) -> None:
    with session_scope() as s:
        p = s.scalar(select(Phase).where(Phase.run_id == run_id, Phase.phase_key == phase_key))
        if p is None:
            return
        p.status = PhaseStatus.running.value
        p.attempt += 1
        p.started_at = utcnow()
        p.ended_at = None
        p.error = ""


def phase_finish(run_id: str, phase_key: str, status: str, *, error: str = "",
                 artifact: dict | None = None, cost_usd: float = 0.0,
                 tokens_in: int = 0, tokens_out: int = 0) -> None:
    with session_scope() as s:
        p = s.scalar(select(Phase).where(Phase.run_id == run_id, Phase.phase_key == phase_key))
        if p is None:
            return
        p.status = status
        p.error = error
        p.ended_at = utcnow()
        if artifact is not None:
            p.artifact = artifact
        p.cost_usd += cost_usd
        p.tokens_in += tokens_in
        p.tokens_out += tokens_out
        run = s.get(Run, run_id)
        if run is not None:
            run.cost_usd += cost_usd
            run.tokens_in += tokens_in
            run.tokens_out += tokens_out


def invalidate_from(run_id: str, phase_key: str) -> list[str]:
    """Reset `phase_key` and everything downstream to pending. Returns the reset keys."""
    with session_scope() as s:
        phases = s.scalars(select(Phase).where(Phase.run_id == run_id)
                           .order_by(Phase.position)).all()
        target = next((p for p in phases if p.phase_key == phase_key), None)
        if target is None:
            return []
        reset = []
        for p in phases:
            if p.position >= target.position:
                p.status = PhaseStatus.pending.value
                p.error = ""
                p.started_at = p.ended_at = None
                reset.append(p.phase_key)
        return reset


def first_incomplete(run_id: str) -> str | None:
    with session_scope() as s:
        p = s.scalar(select(Phase)
                     .where(Phase.run_id == run_id, Phase.status != PhaseStatus.done.value,
                            Phase.status != PhaseStatus.skipped.value)
                     .order_by(Phase.position))
        return p.phase_key if p else None


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
def add_event(run_id: str, event: dict) -> dict:
    """Append an event and return it with its assigned seq + ts."""
    with session_scope() as s:
        seq = (s.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run_id)) or 0) + 1
        row = RunEvent(
            run_id=run_id,
            seq=seq,
            phase_key=event.get("phase_key", "") or "",
            stage=event.get("stage", "log") or "log",
            status=event.get("status", "progress") or "progress",
            msg=str(event.get("msg", ""))[:8000],
            data=event.get("data") or {},
            origin=event.get("origin", "engine") or "engine",
        )
        s.add(row)
        s.flush()
        return event_to_dict(row)


def event_to_dict(e: RunEvent) -> dict:
    return {
        "run_id": e.run_id,
        "seq": e.seq,
        "ts": _iso(e.ts),
        "phase_key": e.phase_key,
        "stage": e.stage,
        "status": e.status,
        "msg": e.msg,
        "data": e.data or {},
        "origin": e.origin,
    }


def events(run_id: str, *, after_seq: int = 0, limit: int = 5000) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(RunEvent)
                         .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                         .order_by(RunEvent.seq).limit(limit)).all()
        return [event_to_dict(e) for e in rows]


# --------------------------------------------------------------------------- #
# Scans
# --------------------------------------------------------------------------- #
def scan_to_dict(scan: Scan) -> dict:
    return {
        "id": scan.id,
        "run_id": scan.run_id,
        "started_at": _iso(scan.started_at),
        "ended_at": _iso(scan.ended_at),
        "mode": scan.mode,
        "engine": scan.engine,
        "jobs_raw": scan.jobs_raw,
        "jobs_after_filter": scan.jobs_after_filter,
        "jobs_scored": scan.jobs_scored,
        "jobs_new": scan.jobs_new,
        "tailored_count": scan.tailored_count,
        "report_path": scan.report_path,
        "source_counts": scan.source_counts or {},
    }


def scan_for_run(run_id: str) -> dict | None:
    with session_scope() as s:
        scan = s.scalar(select(Scan).where(Scan.run_id == run_id))
        return scan_to_dict(scan) if scan else None


def scan_id_for_run(run_id: str) -> int | None:
    with session_scope() as s:
        scan = s.scalar(select(Scan).where(Scan.run_id == run_id))
        return scan.id if scan else None


def update_scan(run_id: str, **fields: Any) -> None:
    with session_scope() as s:
        scan = s.scalar(select(Scan).where(Scan.run_id == run_id))
        if scan is None:
            return
        for k, v in fields.items():
            if hasattr(scan, k):
                setattr(scan, k, v)


def scans(limit: int = 50) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(Scan).order_by(Scan.started_at.desc()).limit(limit)).all()
        return [scan_to_dict(x) for x in rows]
