"""The in-app assistant.

Context is assembled server-side from the user's own database — profile, preferences,
last scan, top matches, applications, recent runs — so a question like "why did Swiss Re
score 78?" can be answered from real data rather than guessed at.

Read-only by design in this release: the assistant explains and summarises. Actions that
change state (starting a run, marking applied, tailoring) stay behind the buttons that
already do them, where the user can see exactly what they're agreeing to.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from auth import get_current_user  # noqa: E402
from core.db import session_scope  # noqa: E402
from core.models import ChatMessage  # noqa: E402
from core.repo import applications as applications_repo  # noqa: E402
from core.repo import cost as cost_repo  # noqa: E402
from core.repo import jobs as jobs_repo  # noqa: E402
from core.repo import profiles as profiles_repo  # noqa: E402
from core.repo import runs as runs_repo  # noqa: E402
from core.repo import settings as settings_repo  # noqa: E402

router = APIRouter(prefix="/api/chat", tags=["chat"])

MAX_HISTORY = 12


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"
    job_id: str | None = None
    run_id: str | None = None


SYSTEM_PROMPT = """You are JobPilot's in-app assistant. JobPilot is a local job-hunting
tool that scrapes job boards, scores every job against the user's resume, and helps them
apply.

You are talking to the person whose job hunt this is. Answer from the CONTEXT below —
it is their real data. If the context doesn't contain the answer, say so plainly rather
than guessing; never invent a job, a score or a number.

How scoring works, so you can explain it accurately:
- `score` (0-100) = half how many of the skills the job asks for the person actually has,
  half an overall judgement of fit. It is what every threshold uses.
- `effective_score` is only for ordering: score x location preference, plus an adjustment
  for how well they fit that company's interview style, plus what past outcomes taught it.
- A "low confidence" score means the job description couldn't be retrieved, so the score
  leans on the title.

Be concise and concrete. Reference specific companies and numbers from the context.
You cannot perform actions — if they want something done, tell them which page does it.
"""


def build_context(user_id: int, job_id: str | None = None, run_id: str | None = None) -> str:
    """Assemble the live picture the assistant reasons over."""
    lines: list[str] = [f"Today: {datetime.now(timezone.utc):%Y-%m-%d}"]

    profile = profiles_repo.current(user_id)
    if profile:
        lines.append(
            f"\nPROFILE: {profile.get('name') or 'unnamed'}, "
            f"{profile.get('experience_years', 0)} years experience. "
            f"Skills: {', '.join(profile.get('skills') or []) or 'none listed'}. "
            f"Confirmed: {profile.get('profile_verified')}."
        )
    else:
        lines.append("\nPROFILE: not built yet.")

    prefs = settings_repo.preferences(user_id)
    lines.append(
        f"PREFERENCES: locations {prefs.get('locations') or '[]'}, "
        f"roles {prefs.get('role_types') or '[]'}, "
        f"minimum package {prefs.get('target_ctc_min_lpa')} LPA, "
        f"tailoring threshold {prefs.get('score_threshold')}."
    )

    stats = jobs_repo.stats(user_id)
    lines.append(
        f"\nJOBS: {stats['total']} recorded ({stats['fresh']} still open), "
        f"average score {stats['avg_score']}, {stats['high_match']} scoring 75+."
    )

    top = jobs_repo.query(user_id, page_size=8, sort="effective_score")["items"]
    if top:
        lines.append("\nTOP MATCHES:")
        for job in top:
            lines.append(
                f"- {job['role']} at {job['company']} ({job['location'] or 'location unknown'}): "
                f"score {job['score']}, ranking {round(job['effective_score'])}, "
                f"matched {', '.join(job['matched_skills'][:5]) or 'none'}; "
                f"missing {', '.join(job['missing_skills'][:5]) or 'none'}; "
                f"salary {job['market_salary'] or 'not researched'}"
                + (f"; applied ({job['application_status']})" if job['application_status'] else "")
            )

    funnel = applications_repo.funnel(user_id)
    if funnel["total"]:
        stages = ", ".join(f"{s['stage']} {s['count']}" for s in funnel["stages"])
        lines.append(f"\nAPPLICATIONS: {funnel['total']} total — {stages}.")

    history = runs_repo.history(user_id, limit=3)
    if history:
        lines.append("\nRECENT RUNS:")
        for run in history:
            lines.append(
                f"- {run['started_at']}: {run['status']}, {run['mode']} mode"
                + (f" — {run['summary']}" if run['summary'] else "")
                + (f" — error: {run['error']}" if run['error'] else "")
            )

    # A job or run the user has open is almost certainly what they're asking about.
    if job_id:
        job = jobs_repo.get(user_id, job_id)
        if job:
            lines.append(
                f"\nTHE JOB THEY ARE LOOKING AT: {job['role']} at {job['company']}. "
                f"score {job['score']} (skills {job['keyword_score']}, "
                f"fit {job['semantic_score']}), ranking {round(job['effective_score'])}. "
                f"Matched: {', '.join(job['matched_skills'])}. "
                f"Missing: {', '.join(job['missing_skills'])}. "
                f"Interview style: {job['archetype'] or 'unknown'}. "
                f"Prep: {job['prep_focus'] or 'none recorded'}. "
                f"Gaps: {job['gap_signals'] or 'none recorded'}."
            )
    if run_id:
        run = runs_repo.get(user_id, run_id)
        if run:
            phases = ", ".join(f"{p['key']}={p['status']}" for p in run["phases"])
            lines.append(
                f"\nTHE RUN THEY ARE LOOKING AT: {run['id']} — {run['status']}. "
                f"Phases: {phases}."
                + (f" Error: {run['error']}" if run["error"] else "")
            )

    spend = cost_repo.summary(user_id, window="month")
    if spend["usd"] or spend["subscription_tokens"]:
        lines.append(
            f"\nCOST (30 days): ${spend['usd']:.2f} metered, "
            f"{spend['subscription_tokens']} subscription tokens."
        )
    return "\n".join(lines)


def _history(user_id: int, conversation_id: str) -> list[dict]:
    from sqlalchemy import select

    with session_scope() as s:
        rows = s.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id, ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(MAX_HISTORY)
        ).all()
    return [
        {"role": r.role, "content": r.content, "at": r.created_at.isoformat()}
        for r in reversed(rows)
    ]


def _store(user_id: int, conversation_id: str, role: str, content: str,
           context: dict | None = None) -> None:
    with session_scope() as s:
        s.add(ChatMessage(user_id=user_id, conversation_id=conversation_id, role=role,
                          content=content, context=context or {}))


@router.get("")
async def get_history(conversation_id: str = "default", user: dict = Depends(get_current_user)):
    return {"messages": _history(user["id"], conversation_id)}


@router.delete("")
async def clear_history(conversation_id: str = "default", user: dict = Depends(get_current_user)):
    from sqlalchemy import delete

    with session_scope() as s:
        s.execute(delete(ChatMessage).where(
            ChatMessage.user_id == user["id"], ChatMessage.conversation_id == conversation_id))
    return {"ok": True, "messages": []}


@router.post("")
async def ask(req: ChatRequest, user: dict = Depends(get_current_user)):
    user_id = user["id"]
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="say something first")

    import engines
    from core import pricing

    engine_name = settings_repo.engine_config(user_id)["provider"]
    try:
        engine = engines.get_engine(engine_name, user_id=user_id)
        ok, reason = engine.available()
        if not ok:
            raise HTTPException(
                status_code=503,
                detail=f"The {engine_name} backend isn't ready: {reason}")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Could not start the backend: {exc}")

    _store(user_id, req.conversation_id, "user", message)

    history = _history(user_id, req.conversation_id)[:-1]
    transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-6:])
    prompt = (
        f"{SYSTEM_PROMPT}\n\nCONTEXT:\n{build_context(user_id, req.job_id, req.run_id)}\n\n"
        + (f"EARLIER IN THIS CONVERSATION:\n{transcript}\n\n" if transcript else "")
        + f"THEIR QUESTION:\n{message}"
    )

    chunks: list[str] = []
    try:
        result = await engine.run(prompt, f"chat-{req.conversation_id}",
                                  lambda ev: chunks.append(ev.msg or ""))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"The backend failed: {exc}")

    answer = (result.artifacts or {}).get("final_text") or "\n".join(chunks).strip()
    if not result.ok or not answer:
        raise HTTPException(status_code=502,
                            detail=result.error or "The backend returned nothing.")

    usd = 0.0
    if result.usage:
        usd, source = pricing.price_usage(result.usage, user_id, engine=engine_name)
        cost_repo.record(
            user_id,
            engine=engine_name, model=getattr(result.usage, "model", "") or "",
            tokens_in=result.usage.tokens_in, tokens_out=result.usage.tokens_out,
            usd=usd, source=source, kind="chat",
        )

    _store(user_id, req.conversation_id, "assistant", answer,
           {"job_id": req.job_id, "run_id": req.run_id, "usd": usd})

    return {"answer": answer, "usd": usd, "messages": _history(user_id, req.conversation_id)}
