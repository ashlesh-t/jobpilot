"""Resume tailoring — the per-job action and the library it fills."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from auth import get_current_user  # noqa: E402
from core import tailoring  # noqa: E402
from core.repo import jobs as jobs_repo  # noqa: E402
from core.repo import profiles as profiles_repo  # noqa: E402
from core.repo import resumes as resumes_repo  # noqa: E402
from core.repo import settings as settings_repo  # noqa: E402
from core.repo import tailored as tailored_repo  # noqa: E402

router = APIRouter(prefix="/api/tailored", tags=["tailoring"])


TAILOR_PROMPT = """You are tailoring a resume to one specific job.

Return ONLY a complete LaTeX document, filled in from the template below. No commentary,
no code fences.

Hard rules:
- Never invent experience, employers, dates, degrees or numbers. Only reorder, reword
  and re-emphasise what the profile already contains.
- Keep the template's structure exactly: same packages, same sections, same commands.
  You are editing content, not layout — the layout is what makes it machine-readable.
- Weave in the skills the job asks for **only** where the profile genuinely supports them.
- Keep it to two pages of content.
- Replace every {{PLACEHOLDER}}.

TEMPLATE:
{template}

CANDIDATE PROFILE (JSON):
{profile}

THE JOB:
Company: {company}
Role: {role}
Skills they ask for: {skills}

JOB DESCRIPTION:
{jd}
"""


@router.get("")
async def list_tailored(user: dict = Depends(get_current_user)):
    from core import backends

    has_tectonic = tailoring.has_tectonic()
    return {"items": tailored_repo.list_all(user["id"]), "count": tailored_repo.count(user["id"]),
            "tectonic": has_tectonic,
            # Shown in the "no PDF compiler" card so the fix is one copyable line.
            "tectonic_hints": [] if has_tectonic else backends.tectonic_install_hints()}


@router.get("/{tailored_id}")
async def get_tailored(tailored_id: int, user: dict = Depends(get_current_user)):
    record = tailored_repo.get(user["id"], tailored_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    record["files"] = tailoring.list_folder(user["id"], record["folder_name"])
    return record


@router.get("/{tailored_id}/download/{kind}")
async def download(tailored_id: int, kind: str, user: dict = Depends(get_current_user)):
    record = tailored_repo.get(user["id"], tailored_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not found")
    path = Path(record["pdf_path"] if kind == "pdf" else record["tex_path"] or "")
    if kind not in ("pdf", "tex") or not path or not path.exists():
        raise HTTPException(status_code=404,
                            detail=f"no {kind} file for this resume")
    if kind == "tex":
        # Served as text so "Copy for Overleaf" can read it straight out of the response.
        return PlainTextResponse(path.read_text(encoding="utf-8"),
                                 headers={"X-Filename": path.name})
    return FileResponse(str(path), filename=path.name)


@router.delete("/{tailored_id}")
async def delete_tailored(tailored_id: int, user: dict = Depends(get_current_user)):
    if not tailored_repo.remove(user["id"], tailored_id):
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "items": tailored_repo.list_all(user["id"])}


@router.post("/jobs/{job_id}")
async def tailor_for_job(job_id: str, user: dict = Depends(get_current_user)):
    """Rewrite the active resume for one job.

    Synchronous by design: it takes seconds, and a background task would need its own
    progress surface for no real benefit.
    """
    job = jobs_repo.get(user["id"], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    profile = profiles_repo.current(user["id"])
    if not profile:
        raise HTTPException(
            status_code=409,
            detail="No profile yet — upload a resume and build your profile first.")

    base = resumes_repo.active(user["id"])
    if base is None:
        raise HTTPException(status_code=409, detail="No active resume to tailor from.")

    jd_skills = list(job.get("matched_skills") or []) + list(job.get("missing_skills") or [])
    engine_name = settings_repo.engine_config(user["id"])["provider"]

    tex_source, cost, detail = await _generate(user["id"], job, profile, engine_name)
    if tex_source is None:
        raise HTTPException(status_code=502, detail=detail)

    record = tailoring.write_result(
        user_id=user["id"],
        job_id=job_id,
        company=job.get("company", ""),
        full_name=profile.get("name", ""),
        tex_source=tex_source,
        jd_skills=jd_skills,
        base_text=base.get("parsed_text") or "",
        engine=engine_name,
        cost_usd=cost,
        base_resume_id=base["id"],
    )
    return record


async def _generate(user_id: int, job: dict, profile: dict,
                    engine_name: str) -> tuple[str | None, float, str]:
    """Ask the agent for the tailored LaTeX. Returns (source, usd, detail)."""
    import json
    import re

    import engines
    from core import pricing
    from core.repo import cost as cost_repo

    try:
        engine = engines.get_engine(engine_name, user_id=user_id)
        ok, reason = engine.available()
        if not ok:
            return None, 0.0, f"The {engine_name} backend isn't ready: {reason}"
    except Exception as exc:  # noqa: BLE001
        return None, 0.0, f"Could not start the AI backend: {exc}"

    clean_profile = {k: v for k, v in profile.items() if not k.startswith("_")}
    prompt = TAILOR_PROMPT.format(
        template=tailoring.load_template(),
        profile=json.dumps(clean_profile, ensure_ascii=False)[:8000],
        company=job.get("company", ""),
        role=job.get("role", ""),
        skills=", ".join((job.get("matched_skills") or []) + (job.get("missing_skills") or [])),
        jd=(job.get("jd_full") or "")[:12000],
    )

    chunks: list[str] = []
    try:
        result = await engine.run(prompt, f"tailor-{job['job_id']}",
                                  lambda ev: chunks.append(ev.msg or ""))
    except Exception as exc:  # noqa: BLE001
        return None, 0.0, f"The AI backend failed: {exc}"

    usd = 0.0
    if result.usage:
        usd, source = pricing.price_usage(result.usage, user_id, engine=engine_name)
        cost_repo.record(
            user_id,
            engine=engine_name, model=getattr(result.usage, "model", "") or "",
            tokens_in=result.usage.tokens_in, tokens_out=result.usage.tokens_out,
            usd=usd, source=source, kind="tailor", phase_key="tailor",
        )

    blob = (result.artifacts or {}).get("final_text") or "\n".join(chunks)
    match = re.search(r"\\documentclass.*?\\end\{document\}", blob, re.S)
    if not result.ok or not match:
        return None, usd, ("The backend didn't return a complete LaTeX document. "
                           "Try again, or check the AI backend on My Info.")
    return match.group(0), usd, "ok"
