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
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from run_manager import manager, RunBusyError  # noqa: E402
from scheduler import scheduler  # noqa: E402
from telegram_auth import tg_auth  # noqa: E402
from doctor import run_doctor  # noqa: E402

UI_DIR = Path(__file__).resolve().parent / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="JobPilot", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class RunRequest(BaseModel):
    mode: str = "auto"            # auto | full | native
    engine: str | None = None


class ConfigRequest(BaseModel):
    engine: dict | None = None            # {provider, model, permission_mode}
    preferences: dict | None = None       # arbitrary prefs to merge
    notify_channels: list[str] | None = None


class SecretRequest(BaseModel):
    key: str
    value: str


class ScheduleRequest(BaseModel):
    slots: list[str]                      # ["09:30", "14:00"]


class TelegramStart(BaseModel):
    phone: str


class TelegramCode(BaseModel):
    token: str
    code: str


class TelegramPassword(BaseModel):
    token: str
    password: str


class DiscordRequest(BaseModel):
    webhook_url: str


class DoneRequest(BaseModel):
    done: bool = True


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
@app.get("/")
async def index():
    idx = UI_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"error": "UI not built"}, status_code=404)


@app.get("/profile-review")
async def profile_review_page():
    page = UI_DIR / "profile_review.html"
    if page.exists():
        return FileResponse(str(page))
    return JSONResponse({"error": "profile review UI not built"}, status_code=404)


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
@app.post("/runs")
async def start_run(req: RunRequest):
    try:
        run = await manager.start_run(mode=req.mode, engine_name=req.engine)
    except RunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run_id": run.id, "status": run.status}


@app.get("/runs")
async def list_runs():
    active = manager.active.to_public() if manager.active else None
    return {"active": active, "history": manager.history()}


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = manager.get(run_id)
    if run:
        return run.to_public()
    # fall back to persisted history
    for h in manager.history(200):
        if h["id"] == run_id:
            return h
    raise HTTPException(status_code=404, detail="run not found")


@app.get("/runs/{run_id}/events")
async def run_events_stream(run_id: str, request: Request):
    run = manager.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found or already evicted")
    q = manager.subscribe(run)

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
            manager.unsubscribe(run, q)

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


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #
@app.get("/schedule")
async def get_schedule():
    return {"slots": load_prefs().get("schedule_slots_ist", []),
            "jobs": scheduler.jobs()}


@app.put("/schedule")
async def put_schedule(req: ScheduleRequest):
    save_prefs({"schedule_slots_ist": req.slots})
    scheduler.reconfigure()
    return {"ok": True, "slots": req.slots, "jobs": scheduler.jobs()}


# --------------------------------------------------------------------------- #
# Connections — Telegram OTP + Discord
# --------------------------------------------------------------------------- #
@app.get("/auth/telegram/status")
async def telegram_status():
    return tg_auth.status()


@app.post("/auth/telegram/start")
async def telegram_start(req: TelegramStart):
    return await tg_auth.start(req.phone)


@app.post("/auth/telegram/code")
async def telegram_code(req: TelegramCode):
    return await tg_auth.submit_code(req.token, req.code)


@app.post("/auth/telegram/password")
async def telegram_password(req: TelegramPassword):
    return await tg_auth.submit_password(req.token, req.password)


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
@app.get("/api/profile")
async def get_profile():
    p = profile_path()
    if not p.exists():
        raise HTTPException(status_code=404, detail="profile.json not found")
    try:
        return json.loads(p.read_text())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"could not parse profile.json: {exc}")


@app.post("/api/profile")
async def post_profile(payload: dict = Body(...)):
    p = profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return {"ok": True, "profile": payload}


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
    return {"ok": True, "active_run": manager.active.id if manager.active else None}
