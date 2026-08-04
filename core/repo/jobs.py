"""Jobs repository — upsert from a scored run, and the filtered/sorted queries the UI needs.

`Job` itself is shared/global (see core/models.py) — company, role, JD text are the same
regardless of who's looking. Everything score/intel/salary-shaped lives per-user on
`JobUserScore`, so every read that includes a score takes `user_id` and left-joins it;
writes that only touch shared listing fields (mark_stale, counts_for_scan, delete) don't.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import case, func, or_, select

from ..db import session_scope
from ..models import Application, Job, JobUserScore, TailoredResume, utcnow
from . import settings as settings_repo

SORTABLE = {
    "score": JobUserScore.score,
    "effective_score": JobUserScore.effective_score,
    "salary": JobUserScore.salary_max_lpa,
    "package": JobUserScore.salary_max_lpa,
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
def upsert_scored(user_id: int, jobs: Iterable[dict], *, scan_id: int | None = None) -> dict[str, int]:
    """Persist scored jobs for `user_id`. Returns {"inserted": n, "updated": n}.

    Mirrors the v1 `record_scored.py` contract: an existing application/tailoring state
    is untouched — only the shared `Job` listing fields and this user's `JobUserScore`
    row are refreshed. Counts reflect whether *this user* had scored the job before, not
    whether the shared `Job` row was new (another user may have already seen it).
    """
    inserted = updated = 0
    now = utcnow()
    with session_scope() as s:
        for j in jobs:
            job_id = (j.get("job_id") or "").strip()
            if not job_id:
                continue
            job = s.get(Job, job_id)
            fresh_job = job is None
            if fresh_job:
                job = Job(job_id=job_id, first_seen=now)
                s.add(job)

            job.company = j.get("company", job.company if not fresh_job else "") or ""
            job.role = j.get("role", job.role if not fresh_job else "") or ""
            job.location = j.get("location", job.location if not fresh_job else "") or ""
            job.source_board = j.get("source_board", job.source_board if not fresh_job else "") or ""
            # Never let a later pass blank out an apply link we already have.
            job.application_url = j.get("application_url") or job.application_url or ""
            job.apply_type = j.get("apply_type") or job.apply_type or ""
            job.jd_full = j.get("jd_full") or job.jd_full or ""
            job.experience_req = str(j.get("experience_req") or job.experience_req or "")
            if j.get("exp_req_years") is not None:
                job.exp_req_years = _f(j.get("exp_req_years"))
            job.posted_date = str(j.get("posted_date") or job.posted_date or "")
            job.last_date = str(j.get("last_date") or job.last_date or "")
            if scan_id is not None:
                job.scan_id = scan_id
            job.last_seen = now
            job.is_stale = False

            score_row = s.get(JobUserScore, (user_id, job_id))
            fresh_score = score_row is None
            if fresh_score:
                score_row = JobUserScore(user_id=user_id, job_id=job_id)
                s.add(score_row)

            salary_text = j.get("market_salary") or j.get("salary_range") or ""
            lo, hi = parse_salary_lpa(salary_text)

            score_row.score = _f(j.get("score"), score_row.score)
            score_row.keyword_score = _f(j.get("keyword_score"), score_row.keyword_score)
            score_row.semantic_score = _f(j.get("semantic_score"), score_row.semantic_score)
            score_row.location_weight = _f(j.get("location_weight"), score_row.location_weight or 1.0)
            score_row.bar_fit = _f(j.get("bar_fit"), score_row.bar_fit)
            score_row.learning_adj = _f(j.get("learning_adj"), score_row.learning_adj)
            # effective_score is sort-order only (CLAUDE.md): score × location_weight,
            # plus the interview-bar and learning adjustments. Never a threshold gate.
            computed = score_row.score * (score_row.location_weight or 1.0) + score_row.bar_fit + score_row.learning_adj
            score_row.effective_score = _f(j.get("effective_score"), computed)
            score_row.score_confidence = j.get("score_confidence") or score_row.score_confidence or ""
            score_row.matched_skills = _as_list(j.get("matched_skills")) or score_row.matched_skills or []
            score_row.missing_skills = _as_list(j.get("missing_skills")) or score_row.missing_skills or []

            score_row.archetype = j.get("archetype") or score_row.archetype or ""
            score_row.prep_focus = j.get("prep_focus") or score_row.prep_focus or ""
            score_row.gap_signals = j.get("gap_signals") or score_row.gap_signals or ""

            score_row.market_salary = salary_text or score_row.market_salary or ""
            score_row.your_demand = j.get("your_demand") or score_row.your_demand or ""
            score_row.salary_source = j.get("salary_source") or score_row.salary_source or ""
            if lo is not None:
                score_row.salary_min_lpa, score_row.salary_max_lpa = lo, hi

            if fresh_score:
                inserted += 1
            else:
                updated += 1
    return {"inserted": inserted, "updated": updated}


def mark_stale(user_id: int, days: int | None = None) -> int:
    """Flag jobs not seen for `days`, or whose apply-by date has passed.

    `is_stale` lives on the shared `Job` row (a listing is gone for everyone at once),
    but the staleness window is a per-user preference — `user_id` picks whose
    `stale_after_days` setting applies.
    """
    if days is None:
        days = int(settings_repo.get(user_id, "stale_after_days", 21) or 21)
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
    since everything else was already in their list. `Job` is shared, so this counts
    listings, not any one user's scoring of them.
    """
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Job)
                         .where(Job.scan_id == scan_id)) or 0
        rows = s.scalars(select(Job).where(Job.scan_id == scan_id)).all()
        new = sum(1 for r in rows if r.first_seen and r.last_seen
                  and abs((r.last_seen - r.first_seen).total_seconds()) < 5)
    return {"total": total, "new": new}


def delete(job_id: str) -> bool:
    """Deletes the shared listing (cascades to every user's score/application/tailoring
    rows for it) — an admin/cleanup operation, not scoped to one user."""
    with session_scope() as s:
        row = s.get(Job, job_id)
        if row is None:
            return False
        s.delete(row)
        return True


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def to_dict(row: Job, *, score: JobUserScore | None = None, application: Application | None = None,
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
        "score": score.score if score else 0.0,
        "keyword_score": score.keyword_score if score else 0.0,
        "semantic_score": score.semantic_score if score else 0.0,
        "effective_score": score.effective_score if score else 0.0,
        "location_weight": score.location_weight if score else 1.0,
        "bar_fit": score.bar_fit if score else 0.0,
        "learning_adj": score.learning_adj if score else 0.0,
        "score_confidence": score.score_confidence if score else "",
        "matched_skills": (score.matched_skills if score else []) or [],
        "missing_skills": (score.missing_skills if score else []) or [],
        "archetype": score.archetype if score else "",
        "prep_focus": score.prep_focus if score else "",
        "gap_signals": score.gap_signals if score else "",
        "market_salary": score.market_salary if score else "",
        "your_demand": score.your_demand if score else "",
        "salary_source": score.salary_source if score else "",
        "salary_min_lpa": score.salary_min_lpa if score else None,
        "salary_max_lpa": score.salary_max_lpa if score else None,
        "scan_id": row.scan_id,
        "first_seen": row.first_seen.isoformat() if row.first_seen else None,
        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        "is_stale": row.is_stale,
        "application_status": application.status if application else None,
        "applied_at": application.applied_at.isoformat() if application else None,
        "tailored_count": len(tailored or []),
        "tailored_folder": (tailored[0].folder_name if tailored else ""),
    }


def _base_stmt(user_id: int):
    """Job left-joined to this user's score row, so an unscored job still lists with
    score fields defaulting to zero (matches pre-split behaviour)."""
    return select(Job, JobUserScore).outerjoin(
        JobUserScore, (JobUserScore.job_id == Job.job_id) & (JobUserScore.user_id == user_id))


def _apply_filters(stmt, f: dict, user_id: int):
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
        stmt = stmt.where(JobUserScore.archetype.in_(f["archetypes"]))
    if f.get("min_score") is not None:
        stmt = stmt.where(JobUserScore.score >= float(f["min_score"]))
    if f.get("max_score") is not None:
        stmt = stmt.where(JobUserScore.score <= float(f["max_score"]))
    if f.get("min_salary") is not None:
        stmt = stmt.where(JobUserScore.salary_max_lpa.isnot(None),
                          JobUserScore.salary_max_lpa >= float(f["min_salary"]))
    if f.get("max_salary") is not None:
        stmt = stmt.where(JobUserScore.salary_min_lpa.isnot(None),
                          JobUserScore.salary_min_lpa <= float(f["max_salary"]))
    if f.get("scan_id"):
        stmt = stmt.where(Job.scan_id == int(f["scan_id"]))
    if f.get("unapplied_only"):
        stmt = stmt.where(~Job.job_id.in_(
            select(Application.job_id).where(Application.user_id == user_id)))
    if f.get("applied_only"):
        stmt = stmt.where(Job.job_id.in_(
            select(Application.job_id).where(Application.user_id == user_id)))
    return stmt


def query(user_id: int, *, page: int = 1, page_size: int = 25, sort: str = "effective_score",
          order: str = "desc", **filters) -> dict:
    """Paged, sorted, filtered job list. Returns {items, total, page, page_size, pages}."""
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    col = SORTABLE.get(sort, JobUserScore.effective_score)
    direction = col.desc() if order.lower() != "asc" else col.asc()

    with session_scope() as s:
        base = _apply_filters(_base_stmt(user_id), filters, user_id)
        total = s.scalar(select(func.count()).select_from(base.subquery())) or 0
        # NULL salaries must not float to the top when sorting by package.
        stmt = base.order_by(direction.nullslast(), Job.job_id).offset((page - 1) * page_size).limit(page_size)
        rows = s.execute(stmt).all()
        job_ids = [job.job_id for job, _ in rows]
        apps = {a.job_id: a for a in s.scalars(
            select(Application).where(Application.user_id == user_id,
                                      Application.job_id.in_(job_ids))).all()} if job_ids else {}
        tail: dict[str, list] = {}
        if job_ids:
            for t in s.scalars(select(TailoredResume).where(
                    TailoredResume.user_id == user_id, TailoredResume.job_id.in_(job_ids))).all():
                tail.setdefault(t.job_id, []).append(t)
        items = [to_dict(job, score=score, application=apps.get(job.job_id), tailored=tail.get(job.job_id))
                 for job, score in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def get(user_id: int, job_id: str) -> dict | None:
    with session_scope() as s:
        row = s.get(Job, job_id)
        if row is None:
            return None
        score = s.get(JobUserScore, (user_id, job_id))
        app = s.scalar(select(Application).where(
            Application.user_id == user_id, Application.job_id == job_id))
        tail = s.scalars(select(TailoredResume).where(
            TailoredResume.user_id == user_id, TailoredResume.job_id == job_id)).all()
        d = to_dict(row, score=score, application=app, tailored=list(tail))
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
    d["contacts"] = contacts_repo.for_company(user_id, company)
    d["referrals"] = referrals_repo.for_job(user_id, job_id)
    return d


def facets(user_id: int) -> dict:
    """Distinct values for the filter dropdowns."""
    with session_scope() as s:
        sources = [r for (r,) in s.execute(
            select(Job.source_board).where(Job.source_board != "").distinct()).all()]
        archetypes = [r for (r,) in s.execute(
            select(JobUserScore.archetype).where(
                JobUserScore.user_id == user_id, JobUserScore.archetype != "").distinct()).all()]
        locations = [r for (r,) in s.execute(
            select(Job.location).where(Job.location != "").distinct().limit(200)).all()]
        rng = s.execute(select(func.min(JobUserScore.salary_min_lpa), func.max(JobUserScore.salary_max_lpa))
                        .where(JobUserScore.user_id == user_id)).one()
    return {
        "sources": sorted(sources),
        "archetypes": sorted(archetypes),
        "locations": sorted(locations),
        "salary_min": rng[0],
        "salary_max": rng[1],
        "sortable": sorted(SORTABLE),
    }


def stats(user_id: int) -> dict:
    """Dashboard KPI numbers, scoped to jobs this user has actually seen/scored."""
    with session_scope() as s:
        seen = select(JobUserScore.job_id).where(JobUserScore.user_id == user_id)
        total = s.scalar(select(func.count()).select_from(Job).where(Job.job_id.in_(seen))) or 0
        fresh = s.scalar(select(func.count()).select_from(Job).where(
            Job.job_id.in_(seen), Job.is_stale.is_(False))) or 0
        avg = s.scalar(select(func.avg(JobUserScore.score)).where(
            JobUserScore.user_id == user_id, JobUserScore.score > 0))
        high = s.scalar(select(func.count()).select_from(JobUserScore).where(
            JobUserScore.user_id == user_id, JobUserScore.score >= 75)) or 0
        by_source = s.execute(
            select(Job.source_board, func.count()).where(Job.job_id.in_(seen))
            .group_by(Job.source_board)).all()
        top_companies = s.execute(
            select(Job.company, func.count(), func.avg(JobUserScore.score))
            .join(JobUserScore, (JobUserScore.job_id == Job.job_id) & (JobUserScore.user_id == user_id))
            .where(Job.company != "").group_by(Job.company)
            .order_by(func.avg(JobUserScore.score).desc()).limit(10)).all()
        bucket_expr = case(
            (JobUserScore.score < 40, "0-39"),
            (JobUserScore.score < 60, "40-59"),
            (JobUserScore.score < 75, "60-74"),
            else_="75-100",
        )
        bucket_counts = dict(s.execute(
            select(bucket_expr.label("b"), func.count())
            .where(JobUserScore.user_id == user_id).group_by("b")).all())
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


def export_rows(user_id: int, **filters) -> list[dict]:
    """All matching jobs, unpaged, for CSV/XLSX export."""
    sort = filters.pop("sort", "effective_score")
    order = filters.pop("order", "desc")
    col = SORTABLE.get(sort, JobUserScore.effective_score)
    direction = col.desc() if order.lower() != "asc" else col.asc()
    with session_scope() as s:
        stmt = _apply_filters(_base_stmt(user_id), filters, user_id).order_by(direction.nullslast())
        rows = s.execute(stmt).all()
        job_ids = [job.job_id for job, _ in rows]
        apps = {a.job_id: a for a in s.scalars(
            select(Application).where(Application.user_id == user_id,
                                      Application.job_id.in_(job_ids))).all()} if job_ids else {}
        return [to_dict(job, score=score, application=apps.get(job.job_id)) for job, score in rows]
