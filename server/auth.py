"""Session-cookie auth for the FastAPI service.

No JWT, no localStorage: a session is a database row (`core.repo.sessions`) and the
browser holds only an opaque token in an HttpOnly cookie. `get_current_user` is the
dependency every data-touching route adds; it resolves the cookie to a user dict or
raises 401 — there is no silent "act as nobody" fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from fastapi import HTTPException, Request  # noqa: E402
from starlette.responses import Response  # noqa: E402

from core.repo import sessions as sessions_repo  # noqa: E402

COOKIE_NAME = "jobpilot_session"

#: Matches core.auth.new_session_expiry()'s horizon — the cookie should not outlive
#: the session row it names.
COOKIE_MAX_AGE_S = 30 * 24 * 3600


def _is_secure(request: Request) -> bool:
    """Secure only when we're actually served over HTTPS — a plain http://127.0.0.1
    dev/local install must still be able to set and read the cookie."""
    if request.url.scheme == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.lower() == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )


def get_current_user(request: Request) -> dict:
    """FastAPI dependency: the logged-in user, or a 401.

    Every route that touches account data (jobs, resumes, runs, settings, secrets, ...)
    should depend on this and pass `user["id"]` into the repo call it makes.
    """
    token = request.cookies.get(COOKIE_NAME, "")
    user = sessions_repo.get_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user
