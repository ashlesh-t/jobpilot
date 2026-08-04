"""Telegram job-channel management — add/remove/list, each validated live.

No auth flow here (see scripts/scrapers/telegram_channels.py's module docstring for
why): a channel is only ever accepted after a real `t.me/s/<channel>` fetch confirms
it's a live public channel. There's no automated discovery — t.me/s/ has no public
search endpoint — so growing the list is a manual, user-driven add.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from auth import get_current_user  # noqa: E402
from core.repo import telegram_channels as tg_channels_repo  # noqa: E402

router = APIRouter(prefix="/api/telegram-channels", tags=["telegram-channels"])


class AddChannelRequest(BaseModel):
    username: str


# Telegram job-channels are an instance-wide source list (not per-account — see the
# module docstring), so these routes are auth-gated but don't thread a user_id through.
@router.get("")
async def list_channels(user: dict = Depends(get_current_user)):
    return {"channels": tg_channels_repo.list_channels()}


@router.post("")
async def add_channel(req: AddChannelRequest, user: dict = Depends(get_current_user)):
    try:
        return tg_channels_repo.add_channel(req.username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/{username}")
async def remove_channel(username: str, user: dict = Depends(get_current_user)):
    if not tg_channels_repo.remove_channel(username):
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}


@router.post("/revalidate")
async def revalidate(user: dict = Depends(get_current_user)):
    return {"channels": tg_channels_repo.revalidate_all()}
