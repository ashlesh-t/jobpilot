"""Referral-message drafting — the per-job action, mirroring routes_tailor.py's shape.

Draft-only, always: the only side effect of POST /jobs/{job_id} is persisting a
drafted message. There is no send/email-dispatch code path anywhere in this file or
in core/repo/referrals.py — the user reviews, edits, and sends it themselves.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from core.repo import contacts as contacts_repo  # noqa: E402
from core.repo import jobs as jobs_repo  # noqa: E402
from core.repo import profiles as profiles_repo  # noqa: E402
from core.repo import referrals as referrals_repo  # noqa: E402
from core.repo import settings as settings_repo  # noqa: E402

router = APIRouter(prefix="/api/referrals", tags=["referrals"])

REFERRAL_PROMPT = """You are drafting a short, warm referral-request message for one
specific job. The candidate will send this themselves — write it so they can copy it
as-is or edit it lightly.

Hard rules:
- Never claim experience, skills or achievements the profile doesn't support.
- Keep it brief: a recruiter or employee reads this in 10 seconds, not a cover letter.
- Reference the specific role and, briefly, why the candidate is a genuine fit — pull
  that from the profile and job description, don't invent it.
- No generic filler ("I am writing to express my interest..."). Sound like a person.
- Return ONLY the message text — no subject line, no commentary, no markdown.

CANDIDATE PROFILE (JSON):
{profile}

CONTACT: {contact_name}, {contact_role} at {company}

THE JOB:
Company: {company}
Role: {role}

JOB DESCRIPTION:
{jd}
"""


class GenerateReferralRequest(BaseModel):
    contact_id: int


class StatusUpdate(BaseModel):
    status: str
    note: str = ""


@router.get("")
async def list_referrals(status: str | None = None):
    return {"items": referrals_repo.list_all(status=status)}


@router.get("/jobs/{job_id}")
async def referrals_for_job(job_id: str):
    return {"items": referrals_repo.for_job(job_id)}


@router.post("/jobs/{job_id}")
async def generate_referral(job_id: str, req: GenerateReferralRequest):
    """Draft a referral message for one job + contact. Persists a `drafted` row and
    returns it — nothing is ever sent."""
    job = jobs_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    contact = contacts_repo.get(req.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")

    profile = profiles_repo.current()
    if not profile:
        raise HTTPException(
            status_code=409,
            detail="No profile yet — upload a resume and build your profile first.")

    engine_name = settings_repo.engine_config()["provider"]
    message, cost, detail = await _generate(job, contact, profile, engine_name)
    if message is None:
        raise HTTPException(status_code=502, detail=detail)

    return referrals_repo.create(job_id, contact["id"], message=message,
                                 engine=engine_name, cost_usd=cost)


@router.patch("/{referral_id}/status")
async def update_referral_status(referral_id: int, req: StatusUpdate):
    try:
        return referrals_repo.set_status(referral_id, req.status, note=req.note)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "no referral" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail)


@router.delete("/{referral_id}")
async def delete_referral(referral_id: int):
    if not referrals_repo.remove(referral_id):
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}


async def _generate(job: dict, contact: dict, profile: dict,
                    engine_name: str) -> tuple[str | None, float, str]:
    """Ask the agent for a drafted message. Returns (message, usd, detail)."""
    import json

    import engines
    from core import pricing
    from core.repo import cost as cost_repo

    try:
        engine = engines.get_engine(engine_name)
        ok, reason = engine.available()
        if not ok:
            return None, 0.0, f"The {engine_name} backend isn't ready: {reason}"
    except Exception as exc:  # noqa: BLE001
        return None, 0.0, f"Could not start the AI backend: {exc}"

    clean_profile = {k: v for k, v in profile.items() if not k.startswith("_")}
    prompt = REFERRAL_PROMPT.format(
        profile=json.dumps(clean_profile, ensure_ascii=False)[:8000],
        contact_name=contact.get("name") or "there",
        contact_role=contact.get("role") or "a contact",
        company=job.get("company", ""),
        role=job.get("role", ""),
        jd=(job.get("jd_full") or "")[:8000],
    )

    chunks: list[str] = []
    try:
        result = await engine.run(prompt, f"referral-{job['job_id']}",
                                  lambda ev: chunks.append(ev.msg or ""))
    except Exception as exc:  # noqa: BLE001
        return None, 0.0, f"The AI backend failed: {exc}"

    usd = 0.0
    if result.usage:
        usd, source = pricing.price_usage(result.usage, engine=engine_name)
        cost_repo.record(
            engine=engine_name, model=getattr(result.usage, "model", "") or "",
            tokens_in=result.usage.tokens_in, tokens_out=result.usage.tokens_out,
            usd=usd, source=source, kind="referral", phase_key="referral",
        )

    message = (result.artifacts or {}).get("final_text") or "\n".join(chunks)
    message = message.strip()
    if not result.ok or not message:
        return None, usd, "The backend didn't return a message. Try again."
    return message, usd, "ok"
