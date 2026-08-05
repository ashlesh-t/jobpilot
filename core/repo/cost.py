"""Cost ledger repository — every metered LLM call, and the roll-ups the UI shows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..db import session_scope
from ..models import CostEntry


def record(user_id: int, *, engine: str, model: str = "", tokens_in: int = 0, tokens_out: int = 0,
           cache_read: int = 0, cache_write: int = 0, usd: float = 0.0,
           source: str = "metered", run_id: str | None = None, phase_key: str = "",
           kind: str = "run") -> dict:
    with session_scope() as s:
        entry = CostEntry(
            user_id=user_id, run_id=run_id, phase_key=phase_key, kind=kind, engine=engine,
            model=model, source=source, tokens_in=tokens_in, tokens_out=tokens_out,
            cache_read=cache_read, cache_write=cache_write, usd=round(usd, 6),
        )
        s.add(entry)
        s.flush()
        return {"id": entry.id, "usd": entry.usd, "tokens_in": entry.tokens_in,
                "tokens_out": entry.tokens_out, "source": entry.source}


def _since(window: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if window == "day":
        return now - timedelta(days=1)
    if window == "week":
        return now - timedelta(days=7)
    if window == "month":
        return now - timedelta(days=30)
    return None


def summary(user_id: int, window: str = "month", run_id: str | None = None) -> dict:
    with session_scope() as s:
        stmt = select(func.coalesce(func.sum(CostEntry.usd), 0.0),
                      func.coalesce(func.sum(CostEntry.tokens_in), 0),
                      func.coalesce(func.sum(CostEntry.tokens_out), 0),
                      func.count()).where(CostEntry.user_id == user_id)
        if run_id:
            stmt = stmt.where(CostEntry.run_id == run_id)
        since = _since(window)
        if since is not None and not run_id:
            stmt = stmt.where(CostEntry.ts >= since)
        usd, tin, tout, calls = s.execute(stmt).one()

        by_kind_stmt = select(CostEntry.kind, func.sum(CostEntry.usd), func.count()) \
            .where(CostEntry.user_id == user_id).group_by(CostEntry.kind)
        if run_id:
            by_kind_stmt = by_kind_stmt.where(CostEntry.run_id == run_id)
        elif since is not None:
            by_kind_stmt = by_kind_stmt.where(CostEntry.ts >= since)
        by_kind = s.execute(by_kind_stmt).all()

        # A subscription run has real tokens but no marginal dollar cost — surface both
        # so the meter never implies a Pro/Max user is being billed per token.
        sub_stmt = select(func.coalesce(func.sum(CostEntry.tokens_in + CostEntry.tokens_out), 0)) \
            .where(CostEntry.user_id == user_id, CostEntry.source == "subscription")
        if run_id:
            sub_stmt = sub_stmt.where(CostEntry.run_id == run_id)
        elif since is not None:
            sub_stmt = sub_stmt.where(CostEntry.ts >= since)
        sub_tokens = s.scalar(sub_stmt) or 0

    return {
        "window": "run" if run_id else window,
        "run_id": run_id,
        "usd": round(float(usd), 4),
        "tokens_in": int(tin),
        "tokens_out": int(tout),
        "calls": int(calls),
        "subscription_tokens": int(sub_tokens),
        "by_kind": [{"kind": k, "usd": round(float(u or 0), 4), "calls": c} for k, u, c in by_kind],
    }


def daily(user_id: int, days: int = 30) -> list[dict]:
    """Per-day spend for the dashboard sparkline."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(func.date(CostEntry.ts), func.sum(CostEntry.usd), func.count())
            .where(CostEntry.user_id == user_id, CostEntry.ts >= since)
            .group_by(func.date(CostEntry.ts))
            .order_by(func.date(CostEntry.ts))).all()
    return [{"date": str(d), "usd": round(float(u or 0), 4), "calls": c} for d, u, c in rows]


def for_run(user_id: int, run_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(CostEntry).where(
            CostEntry.user_id == user_id, CostEntry.run_id == run_id)
            .order_by(CostEntry.ts)).all()
        return [{"phase_key": r.phase_key, "engine": r.engine, "model": r.model,
                 "source": r.source, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                 "usd": round(r.usd, 4), "ts": r.ts.isoformat()} for r in rows]
