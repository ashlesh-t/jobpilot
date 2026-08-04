"""Schedule slots and the background-service controls."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import install_service  # noqa: E402
from auth import get_current_user  # noqa: E402
from core.repo import schedule as schedule_repo  # noqa: E402
from core.repo import settings as settings_repo  # noqa: E402
from scheduler import CATCHUP_GRACE_HOURS, scheduler  # noqa: E402

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class SlotCreate(BaseModel):
    name: str = "slot"
    time: str
    timezone: str = "Asia/Kolkata"
    mode: str = "auto"
    days: str = "*"
    enabled: bool = True


class SlotUpdate(BaseModel):
    name: str | None = None
    time: str | None = None
    timezone: str | None = None
    mode: str | None = None
    days: str | None = None
    enabled: bool | None = None


class GracePatch(BaseModel):
    hours: int


def _payload(user_id: int) -> dict:
    return {
        "slots": schedule_repo.list_all(user_id),
        "jobs": scheduler.jobs(user_id),
        "upcoming": scheduler.next_runs(user_id, 7),
        "running": scheduler.running,
        "catchup_grace_hours": settings_repo.get(user_id, "catchup_grace_hours",
                                                  CATCHUP_GRACE_HOURS),
        "service": {
            "installed": install_service.is_installed(),
            "kind": install_service.platform_kind(),
            "status": install_service.status(),
        },
    }


@router.get("")
async def get_schedule(user: dict = Depends(get_current_user)):
    return _payload(user["id"])


@router.post("/slots")
async def create_slot(req: SlotCreate, user: dict = Depends(get_current_user)):
    try:
        schedule_repo.create(user["id"], name=req.name, time=req.time, timezone=req.timezone,
                             mode=req.mode, days=req.days, enabled=req.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    scheduler.reconfigure()
    return _payload(user["id"])


@router.put("/slots/{slot_id}")
async def update_slot(slot_id: int, req: SlotUpdate, user: dict = Depends(get_current_user)):
    try:
        updated = schedule_repo.update(user["id"], slot_id, **req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="no such schedule slot")
    scheduler.reconfigure()
    return _payload(user["id"])


@router.delete("/slots/{slot_id}")
async def delete_slot(slot_id: int, user: dict = Depends(get_current_user)):
    if not schedule_repo.delete(user["id"], slot_id):
        raise HTTPException(status_code=404, detail="no such schedule slot")
    scheduler.reconfigure()
    return _payload(user["id"])


@router.put("/catchup")
async def set_catchup(req: GracePatch, user: dict = Depends(get_current_user)):
    """0 disables catch-up entirely — some people would rather not be surprised."""
    if req.hours < 0 or req.hours > 72:
        raise HTTPException(status_code=400, detail="grace must be between 0 and 72 hours")
    settings_repo.set(user["id"], "catchup_grace_hours", req.hours, export=False)
    return _payload(user["id"])


@router.post("/service/{action}")
async def service_control(action: str, user: dict = Depends(get_current_user)):
    if action not in ("install", "uninstall"):
        raise HTTPException(status_code=400, detail="expected install or uninstall")
    ok = install_service.install() if action == "install" else install_service.uninstall()
    return {"ok": ok, "service": _payload(user["id"])["service"]}
