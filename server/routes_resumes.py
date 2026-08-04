"""Resume upload, folders, activation — and extracting a profile from one.

This replaces the Google Drive dependency entirely: resumes are uploaded here, kept in
folders the user creates, and exactly one is active. The active resume is what every
scoring and tailoring step reads.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from core.repo import profiles as profiles_repo  # noqa: E402
from core.repo import resumes as resumes_repo  # noqa: E402
from core.repo import settings as settings_repo  # noqa: E402

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

MAX_BYTES = 15 * 1024 * 1024   # a resume that large is a scan, not a document


class FolderRename(BaseModel):
    old: str
    new: str


class LabelPatch(BaseModel):
    label: str


@router.get("")
async def list_resumes():
    return {
        "folders": resumes_repo.folders(),
        "resumes": resumes_repo.list_all(),
        "active": resumes_repo.active(),
        "allowed": sorted(resumes_repo.ALLOWED_SUFFIXES),
    }


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    folder: str = Form("default"),
    label: str = Form(""),
    make_active: bool = Form(True),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in resumes_repo.ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"{suffix or 'that file type'} isn't supported — "
                   f"use {', '.join(sorted(resumes_repo.ALLOWED_SUFFIXES))}",
        )

    # Spool to a temp file first so a half-received upload never lands in the library.
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        size = 0
        while chunk := await file.read(1024 * 256):
            size += len(chunk)
            if size > MAX_BYTES:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=413,
                                    detail="that file is larger than 15 MB")
            tmp.write(chunk)
        temp_path = Path(tmp.name)

    try:
        record = resumes_repo.add(temp_path, folder=folder,
                                  filename=file.filename or temp_path.name,
                                  label=label, make_active=make_active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        temp_path.unlink(missing_ok=True)

    # Keep preferences pointing at the active resume — Layer A reads resume_hash to
    # decide when the score cache is stale.
    if record["is_active"]:
        settings_repo.update_preferences(
            {"resume_path": record["path"], "resume_hash": record["hash"]})

    return {"resume": record, "resumes": resumes_repo.list_all()}


@router.post("/{resume_id}/activate")
async def activate_resume(resume_id: int):
    record = resumes_repo.set_active(resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such resume")
    settings_repo.update_preferences(
        {"resume_path": record["path"], "resume_hash": record["hash"]})
    return {"resume": record, "resumes": resumes_repo.list_all()}


@router.get("/{resume_id}/download")
async def download_resume(resume_id: int):
    record = resumes_repo.get(resume_id)
    if record is None or record["missing"]:
        raise HTTPException(status_code=404, detail="that file is no longer on disk")
    return FileResponse(record["path"], filename=record["filename"])


@router.patch("/{resume_id}")
async def rename_resume(resume_id: int, req: LabelPatch):
    from core.db import session_scope
    from core.models import Resume

    with session_scope() as s:
        row = s.get(Resume, resume_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no such resume")
        row.label = req.label
    return {"resume": resumes_repo.get(resume_id)}


@router.delete("/{resume_id}")
async def delete_resume(resume_id: int):
    if not resumes_repo.remove(resume_id):
        raise HTTPException(status_code=404, detail="no such resume")
    active = resumes_repo.active()
    if active:
        settings_repo.update_preferences(
            {"resume_path": active["path"], "resume_hash": active["hash"]})
    return {"resumes": resumes_repo.list_all(), "active": active}


@router.post("/folders/rename")
async def rename_folder(req: FolderRename):
    try:
        moved = resumes_repo.rename_folder(req.old, req.new)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"moved": moved, "folders": resumes_repo.folders()}


# --------------------------------------------------------------------------- #
# Profile extraction
# --------------------------------------------------------------------------- #
@router.post("/{resume_id}/extract")
async def extract_profile(resume_id: int):
    """Read the resume and propose a profile.

    Text extraction is plain Python; the *understanding* is the agent's job. The result
    is saved unverified — the user reviews and confirms it, because a wrong profile
    quietly degrades every score afterwards.
    """
    record = resumes_repo.get(resume_id)
    if record is None or record["missing"]:
        raise HTTPException(status_code=404, detail="that file is no longer on disk")

    text = await asyncio.to_thread(_extract_text, Path(record["path"]))
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be read from that file. If it's a scanned image, "
                   "upload a text-based PDF or a DOCX instead.",
        )
    resumes_repo.set_parsed_text(resume_id, text)

    proposed, source, detail = await _propose_profile(text)
    saved = profiles_repo.save(proposed, verified=False, resume_id=resume_id,
                               resume_hash=record["hash"])
    return {"profile": saved, "source": source, "detail": detail,
            "characters": len(text)}


def _extract_text(path: Path) -> str:
    """Plain text out of PDF / DOCX / TEX / TXT. Never calls the LLM.

    Delegates to the Layer A parser, which has a pdfplumber fallback for PDFs PyPDF2
    can't read and strips LaTeX markup out of `.tex` sources.
    """
    sys.path.insert(0, str(REPO_DIR / "scripts"))
    try:
        from resume_parser import extract_text
        return extract_text(path)
    except Exception:  # noqa: BLE001 — a missing optional reader must not 500
        return ""


# Kept in step with core.repo.profiles.SKELETON: anything missing here is a field the
# agent never fills, which then silently weakens scoring (interview_readiness feeds
# bar_fit) or the digest.
PROFILE_PROMPT = """Read this resume and return ONLY a JSON object with these keys:
name, email, phone, skills (array of concrete technical skills),
experience_years (number), roles_held (array of {title, company, duration}),
projects (array of {name, stack, description}), education ({degree, college, year}),
publications (array of {title, venue, year}), graduation_date, github_url,
portfolio_url, linkedin_url, locations (array), availability (string),
notice_period_days (number),
interview_readiness ({dsa_level, leetcode_url, system_design, spoken_english}).

Rules:
- Never invent anything. Use "" for a missing string, [] for a missing array,
  {} for a missing object and 0 for a missing number.
- List only skills the resume actually claims, as concrete technologies
  ("PostgreSQL", "FastAPI"), not categories ("backend development").
- experience_years: total professional experience, excluding internships unless that
  is all there is. Use 0 for a fresher.
- interview_readiness: dsa_level is one of "strong", "medium", "weak" or "unknown" —
  infer it only from explicit evidence (a LeetCode/Codeforces profile, competitive
  programming wins, a DSA-heavy role). Use "unknown" otherwise. Same for
  system_design and spoken_english.
- Return the JSON and nothing else.

RESUME:
"""

# A two-page resume is ~5k characters; this is headroom for long academic CVs while
# still bounding the prompt. Truncating at 20k used to silently drop the education and
# projects tail of longer documents.
MAX_RESUME_CHARS = 60000


async def _propose_profile(text: str) -> tuple[dict, str, str]:
    """Ask the configured agent to structure the resume; fall back to regex heuristics.

    Returns (profile, source, detail) — `source` tells the UI whether a human should
    look harder at the result.
    """
    import json
    import re

    try:
        import engines
        from core.repo import settings as settings_lib

        engine = engines.get_engine(settings_lib.engine_config()["provider"])
        ok, reason = engine.available()
        if not ok:
            raise RuntimeError(reason)

        chunks: list[str] = []
        result = await engine.run(
            PROFILE_PROMPT + text[:MAX_RESUME_CHARS], "profile-extract",
            lambda ev: chunks.append(ev.msg or ""),
        )
        blob = (result.artifacts or {}).get("final_text") or "\n".join(chunks)
        match = re.search(r"\{.*\}", blob, re.S)
        if result.ok and match:
            return json.loads(match.group(0)), "agent", "extracted by your AI backend"
    except Exception as exc:  # noqa: BLE001
        fallback_reason = str(exc)
    else:
        fallback_reason = "the agent didn't return usable JSON"

    return (
        _heuristic_profile(text),
        "heuristic",
        f"Read without the AI backend ({fallback_reason}) — check every field.",
    )


def _heuristic_profile(text: str) -> dict:
    """Last-resort extraction so upload never dead-ends. Deliberately conservative."""
    import re

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    phone = re.search(r"(?:\+\d{1,3}[\s-]?)?\d{10}", text)
    github = re.search(r"https?://(?:www\.)?github\.com/[\w-]+", text)
    linkedin = re.search(r"https?://(?:www\.)?linkedin\.com/in/[\w-]+", text)

    known = [
        "Python", "Java", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "C++", "C#",
        "React", "Node.js", "Django", "Flask", "FastAPI", "Spring", "SQL", "PostgreSQL",
        "MySQL", "MongoDB", "Redis", "Kafka", "Docker", "Kubernetes", "AWS", "GCP",
        "Azure", "Terraform", "Git", "CI/CD", "REST", "GraphQL", "gRPC", "Linux",
        "TensorFlow", "PyTorch", "Pandas", "NumPy", "Machine Learning", "LLM", "RAG",
    ]
    lowered = text.lower()
    skills = [s for s in known if s.lower() in lowered]

    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")

    return {
        "name": first_line[:60] if len(first_line) < 60 else "",
        "email": email.group(0) if email else "",
        "phone": phone.group(0) if phone else "",
        "skills": skills,
        "github_url": github.group(0) if github else "",
        "linkedin_url": linkedin.group(0) if linkedin else "",
        "roles_held": [],
        "projects": [],
        "education": {},
        "locations": [],
    }
