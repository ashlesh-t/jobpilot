"""Account endpoints — signup, login, logout, session probe, legacy-account claim.

Every route here defines its own auth boundary (unlike every other router, which is
gated uniformly by `Depends(get_current_user)`), so this module is mounted directly in
app.py without a blanket dependency.

Login is intentionally generic on failure — "invalid username or password" never says
which half was wrong, so the endpoint can't be used to enumerate usernames. Signup is the
one place that can say "username taken": you have to supply a username to hit it, so it
leaks nothing an attacker doesn't already have.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from fastapi import APIRouter, Depends, HTTPException, Request, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from auth import COOKIE_NAME, clear_session_cookie, get_current_user, set_session_cookie  # noqa: E402
from core.repo import sessions as sessions_repo  # noqa: E402
from core.repo import users as users_repo  # noqa: E402

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ClaimRequest(BaseModel):
    username: str
    password: str


def _login(request: Request, response: Response, user: dict) -> dict:
    token = sessions_repo.create(
        user["id"],
        user_agent=request.headers.get("user-agent", ""),
        ip=request.client.host if request.client else "",
    )
    set_session_cookie(response, request, token)
    return user


@router.post("/signup")
async def signup(req: SignupRequest, request: Request, response: Response):
    if not req.username.strip() or not req.password:
        raise HTTPException(status_code=400, detail="username and password are required")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    if users_repo.get_by_username(req.username) is not None:
        raise HTTPException(status_code=409, detail="username taken")

    user = users_repo.create(username=req.username, password=req.password,
                             email=req.email, is_admin=users_repo.count() == 0)
    return _login(request, response, user)


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    user = users_repo.authenticate(req.username, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    users_repo.touch_last_login(user["id"])
    return _login(request, response, user)


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        sessions_repo.revoke(token)
    clear_session_cookie(response, request)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/claim")
async def claim(req: ClaimRequest, user: dict = Depends(get_current_user)):
    """Rename + set a real password on the auto-created legacy account from an upgrade
    backfill. Only works while `must_set_password` is still true."""
    if not user.get("must_set_password"):
        raise HTTPException(status_code=400, detail="this account has already been claimed")
    if not req.username.strip() or not req.password:
        raise HTTPException(status_code=400, detail="username and password are required")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")

    claimed = users_repo.claim_legacy(user["id"], username=req.username, password=req.password)
    if claimed is None:
        raise HTTPException(status_code=400, detail="could not claim this account")
    return claimed
