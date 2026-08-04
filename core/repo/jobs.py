"""Jobs repository — upsert from a scored run, and the filtered/sorted queries the UI needs."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import case, func, or_, select

from ..db import session_scope
from ..models import Application, Job, TailoredResume, utcnow
from . import settings as settings_repo

SORTABLE = {
    "score": Job.score,
    "effective_score": Job.effective_score,
    "salary": Job.salary_max_lpa,
    "package": Job.salary_max_lpa,
    "company": Job.company,
    "role": Job.role,
    "location": Job.location,
    "posted": Job.posted_date,
    "first_seen": Job.first_seen,
    "last_seen": Job.last_seen,
}

# "12-18 LPA", "₹15 LPA", "8 - 12 lakhs", "INR 20,00,000"
_LPA_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh)", re.I)
_LPA_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakh)", re.I)


def parse_salary_lpa(text: str) -> tuple[float | None, float | None]:
    """Best-effort LPA range extraction so the UI can sort by package.

    Returns (min, max); either may be None. Unparseable text yields (None, None) rather
    than a guess — a wrong number would silently corrupt the sort order.
    """
    if not text:
        return None, None
    m = _LPA_RANGE.search(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (lo, hi) if lo <= hi else (hi, lo)
    m = _LPA_SINGLE.search(text)
    if m:
        v = float(m.group(1))
        return v, v
    return None, None


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        return [p.strip() for p in value.split(",") if p.strip()]
    return []


def _f(value: Any, default: Any = 0.0) -> float:
    """Coerce to float, falling back to `default` (itself coerced, None → 0.0).

    Column defaults are applied by the database at flush time, so a not-yet-flushed
    row reads back `None` for numeric fields — hence the two-stage coercion.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(default)
        except (TypeError, ValueError):
            return 0.0


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #
def upsert_scored(jobs: Iterable[dict], *, scan_id: int | None = None) -> dict[str, int]:
    """Persist scored jobs. Returns {"inserted": n, "updated": n}.

    Mirrors the v1 `record_scored.py` contract: an existing row keeps its application
    state and tailoring history — only discovery and scoring fields are refreshed.
    """
    inserted = updated = 0
    now = utcnow()
    with session_scope() as s:
        for j in jobs:
            job_id = (j.get("job_id") or "").strip()
            if not job_id:
                continue
            row = s.get(Job, job_id)
            fresh = row is None
            if fresh:
                row = Job(job_id=job_id, first_seen=now)
                s.add(row)

            salary_text = j.get("market_salary") or j.get("salary_range") or ""
            lo, hi = parse_salary_lpa(salary_text)

            row.company = j.get("company", row.company if not fresh else "") or ""
            row.role = j.get("role", row.role if not fresh else "") or ""
            row.location = j.get("location", row.location if not fresh else "") or ""
            row.source_board = j.get("source_board", row.source_board if not fresh else "") or ""
            # Never let a later pass blank out an apply link we already have.
            row.application_url = j.get("application_url") or row.application_url or ""
            row.apply_type = j.get("apply_type") or row.apply_type or ""
            row.jd_full = j.get("jd_full") or row.jd_full or ""
            row.experience_req = str(j.get("experience_req") or row.experience_req or "")
            if j.get("exp_req_years") is not None:
                row.exp_req_years = _f(j.get("exp_req_years"))
            row.posted_date = str(j.get("posted_date") or row.posted_date or "")
            row.last_date = str(j.get("last_date") or row.last_date or "")

            row.score = _f(j.get("score"), row.score)
            row.keyword_score = _f(j.get("keyword_score"), row.keyword_score)
            row.semantic_score = _f(j.get("semantic_score"), row.semantic_score)
            row.location_weight = _f(j.get("location_weight"), row.location_weight or 1.0)
            row.bar_fit = _f(j.get("bar_fit"), row.bar_fit)
            row.learning_adj = _f(j.get("learning_adj"), row.learning_adj)
            # effective_score is sort-order only (CLAUDE.md): score × location_weight,
            # plus the interview-bar and learning adjustments. Never a threshold gate.
            computed = row.score * (row.location_weight or 1.0) + row.bar_fit + row.learning_adj
            row.effective_score = _f(j.get("effective_score"), computed)
            row.score_confidence = j.get("score_confidence") or row.score_confidence or ""
            row.matched_skills = _as_list(j.get("matched_skills")) or row.matched_skills or []
            row.missing_skills = _as_list(j.get("missing_skills")) or row.missing_skills or []

            row.archetype = j.get("archetype") or row.archetype or ""
            row.prep_focus = j.get("prep_focus") or row.prep_focus or ""
            row.gap_signals = j.get("gap_signals") or row.gap_signals or ""

            row.market_salary = salary_text or row.market_salary or ""
            row.your_demand = j.get("your_demand") or row.your_demand or ""
            row.salary_source = j.get("salary_source") or row.salary_source or ""
            if lo is not None:
                row.salary_min_lpa, row.salary_max_lpa = lo, hi

            if scan_id is not None:
                row.scan_id = scan_id
            row.last_seen = now
            row.is_stale = False

            if fresh:
                inserted += 1
            else:
                updated += 1
    return {"inserted": inserted, "updated": updated}


def mark_stale(days: int | None = None) -> int:
    """Flag jobs not seen for `days`, or whose apply-by date has passed."""
    if days is None:
        days = int(settings_repo.get("stale_after_days", 21) or 21)
    cutoff = utcnow() - timedelta(days=days)
    today = datetime.now(timezone.utc).date().isoformat()
    count = 0
    with session_scope() as s:
        for row in s.scalars(select(Job).where(Job.is_stale.is_(False))).all():
            expired = bool(row.last_date) and row.last_date[:10] < today
            if row.last_seen < cutoff or expired:
                row.is_stale = True
                count += 1
    return count


def counts_for_scan(scan_id: int) -> dict:
    """Totals for one scan, splitting first-time finds from repeats.

    "New" means first seen during this scan — the number the user actually cares about,
    since everything else was already in their list.
    """
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Job)
                         .where(Job.scan_id == scan_id)) or 0
        rows = s.scalars(select(Job).where(Job.scan_id == scan_id)).all()
        new = sum(1 for r in rows if r.first_seen and r.last_seen
                  and abs((r.last_seen - r.first_seen).total_seconds()) < 5)
    return {"total": total, "new": new}


def delete(job_id: str) -> bool:
    with session_scope() as s:
        row = s.get(Job, job_id)
        if row is None:
            return False
        s.delete(row)
        return True


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def to_dict(row: Job, *, application: Application | None = None,
            tailored: list[TailoredResume] | None = None) -> dict:
    return {
        "job_id": row.job_id,
        "company": row.company,
        "role": row.role,
        "location": row.location,
        "source_board": row.source_board,
        "application_url": row.application_url,
        "apply_type": row.apply_type,
        "jd_full": row.jd_full,
        "experience_req": row.experience_req,
        "exp_req_years": row.exp_req_years,
        "posted_date": row.posted_date,
        "last_date": row.last_date,
        "score": row.score,
        "keyword_score": row.keyword_score,
        "semantic_score": row.semantic_score,
        "effective_score": row.effective_score,
        "location_weight": row.location_weight,
        "bar_fit": row.bar_fit,
        "learning_adj": row.learning_adj,
        "score_confidence": row.score_confidence,
        "matched_skills": row.matched_skills or [],
        "missing_skills": row.missing_skills or [],
        "archetype": row.archetype,
        "prep_focus": row.prep_focus,
        "gap_signals": row.gap_signals,
        "market_salary": row.market_salary,
        "your_demand": row.your_demand,
        "salary_source": row.salary_source,
        "salary_min_lpa": row.salary_min_lpa,
        "salary_max_lpa": row.salary_max_lpa,
        "scan_id": row.scan_id,
        "first_seen": row.first_seen.isoformat() if row.first_seen else None,
        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        "is_stale": row.is_stale,
        "application_status": application.status if application else None,
        "applied_at": application.applied_at.isoformat() if application else None,
        "tailored_count": len(tailored or []),
        "tailored_folder": (tailored[0].folder_name if tailored else ""),
    }


def _apply_filters(stmt, f: dict):
    if not f.get("include_stale"):
        stmt = stmt.where(Job.is_stale.is_(False))
    if f.get("search"):
        like = f"%{f['search']}%"
        stmt = stmt.where(or_(Job.company.ilike(like), Job.role.ilike(like),
                              Job.location.ilike(like)))
    if f.get("sources"):
        stmt = stmt.where(Job.source_board.in_(f["sources"]))
    if f.get("locations"):
        clauses = [Job.location.ilike(f"%{loc}%") for loc in f["locations"]]
        stmt = stmt.where(or_(*clauses))
    if f.get("archetypes"):
        stmt = stmt.where(Job.archetype.in_(f["archetypes"]))
    if f.get("min_score") is not None:
        stmt = stmt.where(Job.score >= float(f["min_score"]))
    if f.get("max_score") is not None:
        stmt = stmt.where(Job.score <= float(f["max_score"]))
    if f.get("min_salary") is not None:
        stmt = stmt.where(Job.salary_max_lpa.isnot(None),
                          Job.salary_max_lpa >= float(f["min_salary"]))
    if f.get("max_salary") is not None:
        stmt = stmt.where(Job.salary_min_lpa.isnot(None),
                          Job.salary_min_lpa <= float(f["max_salary"]))
    if f.get("scan_id"):
        stmt = stmt.where(Job.scan_id == int(f["scan_id"]))
    if f.get("unapplied_only"):
        stmt = stmt.where(~Job.job_id.in_(select(Application.job_id)))
    if f.get("applied_only"):
        stmt = stmt.where(Job.job_id.in_(select(Application.job_id)))
    return stmt


def query(*, page: int = 1, page_size: int = 25, sort: str = "effective_score",
          order: str = "desc", **filters) -> dict:
    """Paged, sorted, filtered job list. Returns {items, total, page, page_size, pages}."""
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    col = SORTABLE.get(sort, Job.effective_score)
    direction = col.desc() if order.lower() != "asc" else col.asc()

    with session_scope() as s:
        base = _apply_filters(select(Job), filters)
        total = s.scalar(select(func.count()).select_from(base.subquery())) or 0
        # NULL salaries must not float to the top when sorting by package.
        stmt = base.order_by(direction.nullslast(), Job.job_id).offset((page - 1) * page_size).limit(page_size)
        rows = s.scalars(stmt).all()
        job_ids = [r.job_id for r in rows]
        apps = {a.job_id: a for a in s.scalars(
            select(Application).where(Application.job_id.in_(job_ids))).all()} if job_ids else {}
        tail: dict[str, list] = {}
        if job_ids:
            for t in s.scalars(select(TailoredResume).where(TailoredResume.job_id.in_(job_ids))).all():
                tail.setdefault(t.job_id, []).append(t)
        items = [to_dict(r, application=apps.get(r.job_id), tailored=tail.get(r.job_id)) for r in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def get(job_id: str) -> dict | None:
    with session_scope() as s:
        row = s.get(Job, job_id)
        if row is None:
            return None
        app = s.scalar(select(Application).where(Application.job_id == job_id))
        tail = s.scalars(select(TailoredResume).where(TailoredResume.job_id == job_id)).all()
        d = to_dict(row, application=app, tailored=list(tail))
        d["tailored"] = [
            {"id": t.id, "folder_name": t.folder_name, "pdf_path": t.pdf_path,
             "tex_path": t.tex_path, "created_at": t.created_at.isoformat(),
             "ats_before": t.ats_before, "ats_after": t.ats_after, "status": t.status}
            for t in tail
        ]
        company = row.company

    # Each of these manages its own session_scope() — separate, lightweight reads,
    # not nested in the one above. Lets JobDetail's existing useJob hook pick up both
    # for free, with no new read endpoint.
    from . import contacts as contacts_repo
    from . import referrals as referrals_repo
    d["contacts"] = contacts_repo.for_company(company)
    d["referrals"] = referrals_repo.for_job(job_id)
    return d


def facets() -> dict:
    """Distinct values for the filter dropdowns."""
    with session_scope() as s:
        sources = [r for (r,) in s.execute(
            select(Job.source_board).where(Job.source_board != "").distinct()).all()]
        archetypes = [r for (r,) in s.execute(
            select(Job.archetype).where(Job.archetype != "").distinct()).all()]
        locations = [r for (r,) in s.execute(
            select(Job.location).where(Job.location != "").distinct().limit(200)).all()]
        rng = s.execute(select(func.min(Job.salary_min_lpa), func.max(Job.salary_max_lpa))).one()
    return {
        "sources": sorted(sources),
        "archetypes": sorted(archetypes),
        "locations": sorted(locations),
        "salary_min": rng[0],
        "salary_max": rng[1],
        "sortable": sorted(SORTABLE),
    }


def stats() -> dict:
    """Dashboard KPI numbers."""
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Job)) or 0
        fresh = s.scalar(select(func.count()).select_from(Job).where(Job.is_stale.is_(False))) or 0
        avg = s.scalar(select(func.avg(Job.score)).where(Job.score > 0))
        high = s.scalar(select(func.count()).select_from(Job).where(Job.score >= 75)) or 0
        by_source = s.execute(
            select(Job.source_board, func.count()).group_by(Job.source_board)).all()
        top_companies = s.execute(
            select(Job.company, func.count(), func.avg(Job.score))
            .where(Job.company != "").group_by(Job.company)
            .order_by(func.avg(Job.score).desc()).limit(10)).all()
        bucket_expr = case(
            (Job.score < 40, "0-39"),
            (Job.score < 60, "40-59"),
            (Job.score < 75, "60-74"),
            else_="75-100",
        )
        bucket_counts = dict(s.execute(
            select(bucket_expr.label("b"), func.count()).group_by("b")).all())
    return {
        "total": total,
        "fresh": fresh,
        "stale": total - fresh,
        "avg_score": round(float(avg), 1) if avg else 0.0,
        "high_match": high,
        "by_source": [{"source": s_ or "unknown", "count": c} for s_, c in by_source],
        "top_companies": [{"company": c, "count": n, "avg_score": round(float(a or 0), 1)}
                          for c, n, a in top_companies],
        "score_buckets": [{"range": b, "count": bucket_counts.get(b, 0)}
                          for b in ("0-39", "40-59", "60-74", "75-100")],
    }


def export_rows(**filters) -> list[dict]:
    """All matching jobs, unpaged, for CSV/XLSX export."""
    sort = filters.pop("sort", "effective_score")
    order = filters.pop("order", "desc")
    col = SORTABLE.get(sort, Job.effective_score)
    direction = col.desc() if order.lower() != "asc" else col.asc()
    with session_scope() as s:
        stmt = _apply_filters(select(Job), filters).order_by(direction.nullslast())
        rows = s.scalars(stmt).all()
        job_ids = [r.job_id for r in rows]
        apps = {a.job_id: a for a in s.scalars(
            select(Application).where(Application.job_id.in_(job_ids))).all()} if job_ids else {}
        return [to_dict(r, application=apps.get(r.job_id)) for r in rows]
