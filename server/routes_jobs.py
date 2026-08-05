"""Jobs, scans, applications and dashboard endpoints.

Split out of app.py because these are the busiest routes in the product and deserve to
be readable on their own. All query construction lives in `core.repo` — this module only
translates HTTP into repository calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from auth import get_current_user  # noqa: E402
from core import export as export_lib  # noqa: E402
from core.repo import applications as applications_repo  # noqa: E402
from core.repo import cost as cost_repo  # noqa: E402
from core.repo import jobs as jobs_repo  # noqa: E402
from core.repo import runs as runs_repo  # noqa: E402
from core.repo import tailored as tailored_repo  # noqa: E402

router = APIRouter(prefix="/api", tags=["jobs"])


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class ApplyRequest(BaseModel):
    note: str = ""


class StatusRequest(BaseModel):
    status: str
    note: str = ""


class NotesRequest(BaseModel):
    notes: str


def _filters(
    search: str | None,
    sources: list[str] | None,
    locations: list[str] | None,
    archetypes: list[str] | None,
    min_score: float | None,
    max_score: float | None,
    min_salary: float | None,
    max_salary: float | None,
    scan_id: int | None,
    include_stale: bool,
    unapplied_only: bool,
    applied_only: bool,
) -> dict:
    return {
        "search": search,
        "sources": sources,
        "locations": locations,
        "archetypes": archetypes,
        "min_score": min_score,
        "max_score": max_score,
        "min_salary": min_salary,
        "max_salary": max_salary,
        "scan_id": scan_id,
        "include_stale": include_stale,
        "unapplied_only": unapplied_only,
        "applied_only": applied_only,
    }


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
@router.get("/jobs")
async def list_jobs(
    page: int = 1,
    page_size: int = Query(25, le=200),
    sort: str = "effective_score",
    order: str = "desc",
    search: str | None = None,
    sources: list[str] | None = Query(None),
    locations: list[str] | None = Query(None),
    archetypes: list[str] | None = Query(None),
    min_score: float | None = None,
    max_score: float | None = None,
    min_salary: float | None = None,
    max_salary: float | None = None,
    scan_id: int | None = None,
    include_stale: bool = False,
    unapplied_only: bool = False,
    applied_only: bool = False,
    user: dict = Depends(get_current_user),
):
    return jobs_repo.query(
        user["id"], page=page, page_size=page_size, sort=sort, order=order,
        **_filters(search, sources, locations, archetypes, min_score, max_score,
                   min_salary, max_salary, scan_id, include_stale,
                   unapplied_only, applied_only),
    )


@router.get("/jobs/facets")
async def job_facets(user: dict = Depends(get_current_user)):
    """Distinct values for the filter controls."""
    return jobs_repo.facets(user["id"])


@router.get("/jobs/stats")
async def job_stats(user: dict = Depends(get_current_user)):
    """The dashboard's headline numbers and chart series."""
    stats = jobs_repo.stats(user["id"])
    stats["funnel"] = applications_repo.funnel(user["id"])
    stats["tailored"] = tailored_repo.count(user["id"])
    stats["cost_month"] = cost_repo.summary(user["id"], window="month")
    return stats


@router.get("/jobs/export")
async def export_jobs(
    format: str = "csv",
    sort: str = "effective_score",
    order: str = "desc",
    search: str | None = None,
    sources: list[str] | None = Query(None),
    locations: list[str] | None = Query(None),
    archetypes: list[str] | None = Query(None),
    min_score: float | None = None,
    max_score: float | None = None,
    min_salary: float | None = None,
    max_salary: float | None = None,
    scan_id: int | None = None,
    include_stale: bool = False,
    unapplied_only: bool = False,
    applied_only: bool = False,
    user: dict = Depends(get_current_user),
):
    """Download exactly the rows currently on screen — same filters, same order."""
    rows = jobs_repo.export_rows(
        user["id"], sort=sort, order=order,
        **_filters(search, sources, locations, archetypes, min_score, max_score,
                   min_salary, max_salary, scan_id, include_stale,
                   unapplied_only, applied_only),
    )
    content, media_type, filename = export_lib.export(rows, format, title="Jobs")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    job = jobs_repo.get(user["id"], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/jobs/refresh-stale")
async def refresh_stale(days: int | None = None, user: dict = Depends(get_current_user)):
    """Recompute which jobs are stale. Runs after every scan; exposed for manual use."""
    return {"marked": jobs_repo.mark_stale(user["id"], days)}


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
@router.get("/applications")
async def list_applications(status: str | None = None, user: dict = Depends(get_current_user)):
    return {
        "items": applications_repo.list_all(user["id"], status=status),
        "statuses": applications_repo.VALID_STATUSES,
        "pipeline": applications_repo.PIPELINE,
        "terminal": applications_repo.TERMINAL,
    }


@router.get("/applications/board")
async def application_board(user: dict = Depends(get_current_user)):
    return {"columns": applications_repo.board(user["id"]),
            "funnel": applications_repo.funnel(user["id"])}


@router.get("/applications/stale")
async def stale_applications(days: int = 14, user: dict = Depends(get_current_user)):
    return {"items": applications_repo.stale(user["id"], days), "days": days}


@router.post("/jobs/{job_id}/apply")
async def mark_applied(job_id: str, req: ApplyRequest, user: dict = Depends(get_current_user)):
    try:
        return applications_repo.mark_applied(user["id"], job_id, note=req.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/jobs/{job_id}/apply")
async def unmark_applied(job_id: str, user: dict = Depends(get_current_user)):
    """The Undo path — removes the application entirely."""
    if not applications_repo.unmark(user["id"], job_id):
        raise HTTPException(status_code=404, detail="no application for that job")
    return {"ok": True, "job_id": job_id}


@router.put("/jobs/{job_id}/application")
async def set_application_status(job_id: str, req: StatusRequest,
                                 user: dict = Depends(get_current_user)):
    try:
        return applications_repo.set_status(user["id"], job_id, req.status, note=req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/jobs/{job_id}/application/notes")
async def set_application_notes(job_id: str, req: NotesRequest,
                                user: dict = Depends(get_current_user)):
    try:
        return applications_repo.set_notes(user["id"], job_id, req.notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# --------------------------------------------------------------------------- #
# Scans
# --------------------------------------------------------------------------- #
@router.get("/scans")
async def list_scans(limit: int = 50, user: dict = Depends(get_current_user)):
    return {"scans": runs_repo.scans(user["id"], limit)}


@router.get("/scans/{scan_id}/export")
async def export_scan(scan_id: int, format: str = "xlsx", user: dict = Depends(get_current_user)):
    """Everything one scan found, as it was scored at the time."""
    rows = jobs_repo.export_rows(user["id"], scan_id=scan_id, include_stale=True)
    if not rows:
        raise HTTPException(status_code=404, detail="that scan has no jobs recorded")
    content, media_type, filename = export_lib.export(
        rows, format, title=f"Scan {scan_id}")
    filename = filename.replace("jobpilot-jobs", f"jobpilot-scan-{scan_id}")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
