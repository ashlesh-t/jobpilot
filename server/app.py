"""JobPilot local service — FastAPI.

Binds to 127.0.0.1 by default. Serves the control SPA and the JSON/SSE API that drives
the live run view, setup, scheduling, and connections.

Run:  python -m server         (or: uvicorn server.app:app --port 8787)
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Wire import paths (also imported for side effects by the modules below).
from common import (  # noqa: E402
    REPO_DIR, load_prefs, save_prefs, engine_config,
    profile_path, profile_review_done_path,
)

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from run_manager import manager, RunBusyError, UnknownRunError  # noqa: E402
from scheduler import scheduler  # noqa: E402
from doctor import run_doctor  # noqa: E402

def _ui_dir() -> Path:
    """The built React bundle.

    Installed from a wheel it lives at jobpilot/bundle/ui_dist; in a checkout it's
    ui/dist. Returns whichever exists so `jobpilot serve` works from either.
    """
    for candidate in (REPO_DIR / "ui_dist", REPO_DIR / "ui" / "dist"):
        if (candidate / "index.html").exists():
            return candidate
    return REPO_DIR / "ui" / "dist"


UI_DIR = _ui_dir()


def _app_version() -> str:
    from core.version import app_version
    return app_version()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.db import init_db
    init_db()                      # apply any migrations shipped since the last start
    manager.reset_orphans()        # a run left "running" by a crash is not still running
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="JobPilot", lifespan=lifespan)

from routes_jobs import router as jobs_router  # noqa: E402
from routes_settings import router as settings_router  # noqa: E402
from routes_schedule import router as schedule_router  # noqa: E402
from routes_resumes import router as resumes_router  # noqa: E402
from routes_tailor import router as tailor_router  # noqa: E402
from routes_chat import router as chat_router  # noqa: E402
from routes_about import router as about_router  # noqa: E402
from routes_telegram_channels import router as telegram_channels_router  # noqa: E402
from routes_contacts import router as contacts_router  # noqa: E402
from routes_referrals import router as referrals_router  # noqa: E402

app.include_router(jobs_router)
app.include_router(settings_router)
app.include_router(schedule_router)
app.include_router(resumes_router)
app.include_router(tailor_router)
app.include_router(chat_router)
app.include_router(about_router)
app.include_router(telegram_channels_router)
app.include_router(contacts_router)
app.include_router(referrals_router)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class RunRequest(BaseModel):
    mode: str = "auto"            # auto | full | native
    engine: str | None = None
    only: list[str] | None = None   # run just these phases
    skip: list[str] | None = None   # run everything except these


class ConfigRequest(BaseModel):
    engine: dict | None = None            # {provider, model, permission_mode}
    preferences: dict | None = None       # arbitrary prefs to merge
    notify_channels: list[str] | None = None


class SecretRequest(BaseModel):
    key: str
    value: str


class DiscordRequest(BaseModel):
    webhook_url: str


class DoneRequest(BaseModel):
    done: bool = True


class PhaseConfigEntry(BaseModel):
    enabled: bool = True
    model: str | None = None


class PipelineRequest(BaseModel):
    phases: dict[str, PhaseConfigEntry]


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
@app.get("/profile-review", include_in_schema=False)
async def profile_review_page():
    """The standalone profile-review page used by /job-setup.

    Still the v1 single-file page: it is opened by `python -m server.ephemeral` outside
    the SPA, and is replaced by the in-app setup wizard in the Job Hunt epic. Registered
    explicitly so the SPA catch-all below doesn't swallow it.
    """
    page = Path(__file__).resolve().parent / "ui" / "profile_review.html"
    if page.exists():
        return FileResponse(str(page))
    return JSONResponse({"error": "profile review page not found"}, status_code=404)


@app.get("/api/cost")
async def cost_summary(window: str = "month", run_id: str | None = None):
    from core.repo import cost as cost_repo
    return cost_repo.summary(window=window, run_id=run_id)


@app.get("/api/cost/daily")
async def cost_daily(days: int = 30):
    from core.repo import cost as cost_repo
    return {"days": cost_repo.daily(days)}


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
@app.get("/phases")
async def list_phases():
    """The phase catalog the UI renders before and during a run."""
    return {"phases": manager.catalog()}


@app.get("/models")
async def list_models(engine: str | None = None):
    """The selectable models for one engine (or every engine, keyed by name), used by
    the pipeline editor's per-phase model dropdown. Each entry's `tier` says which
    Phase.model_tier it satisfies; "max" (Opus) is opt-in only, never a tier default."""
    from core import model_catalog
    if engine:
        return {"models": model_catalog.models_for(engine)}
    return {"models": model_catalog.CATALOG}


@app.get("/pipeline")
async def get_pipeline():
    """Every phase's saved {enabled, model} — what the next hunt (from the UI or the
    scheduler) will run with. `model: null` means "use this phase's tier default for
    whichever engine is active"."""
    from core.repo import settings as settings_repo
    return {"phases": settings_repo.pipeline_phase_config()}


@app.put("/pipeline")
async def put_pipeline(req: PipelineRequest):
    """Save the choices built in the pipeline editor."""
    from core.repo import settings as settings_repo
    try:
        saved = settings_repo.set_pipeline_phase_config(
            {key: entry.model_dump() for key, entry in req.phases.items()})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"phases": saved}


@app.post("/runs")
async def start_run(req: RunRequest):
    try:
        run = await manager.start_run(mode=req.mode, engine_name=req.engine,
                                      only=req.only, skip=req.skip)
    except RunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run["id"], "status": run["status"], "phases": run["phases"]}


@app.get("/runs")
async def list_runs(limit: int = 50, offset: int = 0):
    return {"active": manager.active(), "history": manager.history(limit, offset)}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    run["top_jobs"] = manager.top_jobs(run_id)
    return run


@app.post("/runs/{run_id}/stop")
async def stop_run(run_id: str):
    run = await manager.stop(run_id)
    if run is None:
        raise HTTPException(status_code=409, detail="that run is not active")
    return run


@app.post("/runs/{run_id}/resume")
async def resume_run(run_id: str):
    try:
        return await manager.resume(run_id)
    except UnknownRunError:
        raise HTTPException(status_code=404, detail="run not found")
    except RunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/runs/{run_id}/phases/{phase_key}/rerun")
async def rerun_phase(run_id: str, phase_key: str):
    try:
        return await manager.rerun_phase(run_id, phase_key)
    except UnknownRunError:
        raise HTTPException(status_code=404, detail="run not found")
    except RunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/runs/{run_id}/artifacts")
async def run_artifacts(run_id: str):
    if manager.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"artifacts": manager.artifacts(run_id)}


@app.get("/runs/{run_id}/artifacts/{name}")
async def run_artifact(run_id: str, name: str):
    from orchestrator.artifacts import ArtifactStore, KNOWN

    if name not in KNOWN:
        raise HTTPException(status_code=404, detail=f"unknown artifact {name!r}")
    path = ArtifactStore(run_id).path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(str(path), media_type="application/json", filename=path.name)


@app.get("/runs/{run_id}/events")
async def run_events_stream(run_id: str, request: Request, after: int = 0):
    """Live event stream. History replays first, so a late or reconnecting client
    still sees the whole timeline — including for runs that already finished."""
    if manager.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    q = manager.subscribe(run_id, after_seq=after)

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                if ev is None:
                    yield {"event": "end", "data": "{}"}
                    break
                yield {"event": "message", "data": json.dumps(ev, ensure_ascii=False)}
        finally:
            manager.unsubscribe(run_id, q)

    return EventSourceResponse(gen())


# --------------------------------------------------------------------------- #
# Config / engines / secrets
# --------------------------------------------------------------------------- #
@app.get("/config")
async def get_config():
    prefs = load_prefs()
    return {"engine": engine_config(),
            "notify_channels": prefs.get("notify_channels", ["telegram"]),
            "preferences": prefs}


@app.put("/config")
async def put_config(req: ConfigRequest):
    patch: dict = {}
    if req.engine is not None:
        patch["engine"] = req.engine
    if req.notify_channels is not None:
        patch["notify_channels"] = req.notify_channels
    if req.preferences:
        patch.update(req.preferences)
    if patch:
        save_prefs(patch)
    return {"ok": True, "config": (await get_config())}


@app.get("/engines")
async def get_engines():
    import engines  # noqa
    return {"engines": engines.list_engines(), "default": engines.DEFAULT_ENGINE}


@app.get("/notifiers")
async def get_notifiers():
    import notify  # noqa
    return {"notifiers": notify.list_notifiers()}


@app.post("/secrets")
async def set_secret_endpoint(req: SecretRequest):
    from jp_secrets import set_secret  # noqa (scripts/secrets.py)
    backend = set_secret(req.key, req.value)
    return {"ok": True, "backend": backend, "key": req.key}


@app.post("/notify/discord")
async def save_discord(req: DiscordRequest):
    from jp_secrets import set_secret  # noqa
    set_secret("DISCORD_WEBHOOK_URL", req.webhook_url)
    import notify  # noqa
    n = notify.get_notifier("discord")
    ok, reason = n.available()
    if not ok:
        return {"ok": False, "error": reason}
    try:
        n.test()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"saved but test failed: {exc}"}
    return {"ok": True, "tested": True}


@app.post("/notify/test/{channel}")
async def notify_test(channel: str):
    import notify  # noqa
    try:
        n = notify.get_notifier(channel)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    ok, reason = n.available()
    if not ok:
        return {"ok": False, "error": reason}
    try:
        n.test()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Profile review — /job-setup opens this so the user can check/edit the profile
# Claude drafted from the resume before it's marked profile_verified: true.
# --------------------------------------------------------------------------- #
@app.get("/api/profile/done")
async def get_profile_done():
    return {"done": profile_review_done_path().exists()}


@app.post("/api/profile/done")
async def set_profile_done(req: DoneRequest):
    marker = profile_review_done_path()
    if req.done:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1")
    else:
        marker.unlink(missing_ok=True)
    return {"ok": True, "done": req.done}


# --------------------------------------------------------------------------- #
# Doctor
# --------------------------------------------------------------------------- #
@app.get("/doctor")
async def doctor(live: bool = False):
    return await asyncio.to_thread(run_doctor, live)


@app.get("/health")
async def health():
    active = manager.active()
    return {"ok": True, "active_run": active["id"] if active else None,
            "version": _app_version()}


# --------------------------------------------------------------------------- #
# Static UI (must be registered last — the SPA fallback matches everything)
# --------------------------------------------------------------------------- #
if (UI_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(UI_DIR / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    """Serve the React app for any non-API path.

    The UI uses real browser routing, so a deep link like /hunt/20260801T093000 must
    return index.html rather than 404 — React then reads the URL and renders that page.
    """
    candidate = (UI_DIR / full_path).resolve()
    try:
        inside = candidate.is_relative_to(UI_DIR.resolve())
    except AttributeError:  # pragma: no cover - Python < 3.9
        inside = str(candidate).startswith(str(UI_DIR.resolve()))
    if full_path and inside and candidate.is_file():
        return FileResponse(str(candidate))

    index = UI_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse(
        {"error": "The web UI isn't built. Run `npm --prefix ui install && "
                  "npm --prefix ui run build`, or reinstall jobpilot-ai."},
        status_code=503,
    )
