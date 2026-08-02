"""Tailored-resume repository.

Output contract (fixed, the UI and Telegram both rely on it):

    resumes/tailored/<JOBID>-<COMPANYNAME>/
        FirstName_LastName_Resume.pdf
        FirstName_LastName_Resume.tex      # Overleaf-ready
        meta.json
"""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select

from ..db import session_scope
from ..models import Job, TailoredResume
from ..paths import tailored_dir

_SLUG = re.compile(r"[^A-Za-z0-9]+")


def folder_name(job_id: str, company: str) -> str:
    slug = _SLUG.sub("", (company or "company").title()) or "Company"
    return f"{job_id}-{slug}"


def resume_basename(full_name: str) -> str:
    """`Ashlesh Tiwari` → `Ashlesh_Tiwari_Resume`. Falls back to a generic name."""
    parts = [p for p in _SLUG.sub(" ", full_name or "").split() if p]
    if not parts:
        return "Resume"
    return "_".join(p.capitalize() for p in parts[:3]) + "_Resume"


def folder_for(job_id: str, company: str) -> Path:
    return tailored_dir() / folder_name(job_id, company)


def _iso(dt):
    return dt.isoformat() if dt else None


def to_dict(t: TailoredResume, job: Job | None = None) -> dict:
    pdf = Path(t.pdf_path) if t.pdf_path else None
    return {
        "id": t.id,
        "job_id": t.job_id,
        "folder_name": t.folder_name,
        "folder_path": str(tailored_dir() / t.folder_name),
        "pdf_path": t.pdf_path,
        "tex_path": t.tex_path,
        "docx_path": t.docx_path,
        "has_pdf": bool(pdf and pdf.exists()),
        "has_tex": bool(t.tex_path and Path(t.tex_path).exists()),
        "ats_before": t.ats_before,
        "ats_after": t.ats_after,
        "engine": t.engine,
        "cost_usd": round(t.cost_usd, 4),
        "status": t.status,
        "error": t.error,
        "meta": t.meta or {},
        "created_at": _iso(t.created_at),
        "company": job.company if job else "",
        "role": job.role if job else "",
        "score": job.score if job else 0.0,
        "application_url": job.application_url if job else "",
    }


def upsert(job_id: str, *, company: str = "", pdf_path: str = "", tex_path: str = "",
           docx_path: str = "", ats_before: float | None = None,
           ats_after: float | None = None, engine: str = "", cost_usd: float = 0.0,
           status: str = "done", error: str = "", meta: dict | None = None,
           base_resume_id: int | None = None) -> dict:
    with session_scope() as s:
        job = s.get(Job, job_id)
        name = folder_name(job_id, company or (job.company if job else ""))
        row = s.scalar(select(TailoredResume).where(TailoredResume.folder_name == name))
        if row is None:
            row = TailoredResume(job_id=job_id, folder_name=name)
            s.add(row)
        if pdf_path:
            row.pdf_path = pdf_path
        if tex_path:
            row.tex_path = tex_path
        if docx_path:
            row.docx_path = docx_path
        if ats_before is not None:
            row.ats_before = ats_before
        if ats_after is not None:
            row.ats_after = ats_after
        if base_resume_id is not None:
            row.base_resume_id = base_resume_id
        row.engine = engine or row.engine
        row.cost_usd = cost_usd or row.cost_usd
        row.status = status
        row.error = error
        if meta is not None:
            row.meta = meta
        s.flush()
        return to_dict(row, job)


def get(tailored_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(TailoredResume, tailored_id)
        if row is None:
            return None
        return to_dict(row, s.get(Job, row.job_id))


def for_job(job_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(TailoredResume).where(TailoredResume.job_id == job_id)
                         .order_by(TailoredResume.created_at.desc())).all()
        job = s.get(Job, job_id)
        return [to_dict(r, job) for r in rows]


def list_all(limit: int = 500) -> list[dict]:
    with session_scope() as s:
        rows = s.execute(
            select(TailoredResume, Job)
            .outerjoin(Job, Job.job_id == TailoredResume.job_id)
            .order_by(TailoredResume.created_at.desc()).limit(limit)).all()
        return [to_dict(t, j) for t, j in rows]


def count() -> int:
    from sqlalchemy import func
    with session_scope() as s:
        return s.scalar(select(func.count()).select_from(TailoredResume)) or 0


def remove(tailored_id: int, *, delete_files: bool = True) -> bool:
    import shutil
    with session_scope() as s:
        row = s.get(TailoredResume, tailored_id)
        if row is None:
            return False
        folder = tailored_dir() / row.folder_name
        s.delete(row)
        s.flush()
        if delete_files and folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        return True
