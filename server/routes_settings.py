"""Profile, preferences, credentials and health-check endpoints — the My Info page.

Credential rule, enforced here: a secret's value is **never** included in a list
response. `GET /api/secrets` returns presence plus a mask; the plaintext is only ever
returned by the explicit `POST /api/secrets/{key}/reveal`, which the UI puts behind a
confirmation. Values are written through the OS keyring and never touch the database.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from core import backends, secrets as secrets_lib  # noqa: E402
from core.repo import profiles as profiles_repo  # noqa: E402
from core.repo import resumes as resumes_repo  # noqa: E402
from core.repo import settings as settings_repo  # noqa: E402

router = APIRouter(prefix="/api", tags=["settings"])


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class SecretValue(BaseModel):
    value: str


class ProfilePatch(BaseModel):
    data: dict
    verified: bool | None = None


class PreferencesPatch(BaseModel):
    preferences: dict


class BackendChoice(BaseModel):
    backend: str


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
@router.get("/profile")
async def get_profile():
    """The candidate profile. Returns the empty skeleton rather than 404 so the form
    always has a shape to render."""
    profile = profiles_repo.current()
    return {
        "profile": profile or profiles_repo.get_or_empty(),
        "exists": profile is not None,
        "verified": bool(profile and profile.get("profile_verified")),
    }


@router.put("/profile")
async def put_profile(req: ProfilePatch):
    saved = profiles_repo.save(req.data, verified=req.verified)
    return {"profile": saved, "verified": saved.get("profile_verified", False)}


@router.post("/profile/verify")
async def verify_profile(confirm: bool = True):
    """Confirming the profile is a deliberate act — scoring quality depends on it."""
    return {"profile": profiles_repo.set_verified(confirm)}


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #
@router.get("/preferences")
async def get_preferences():
    return {
        "preferences": settings_repo.preferences(),
        "setup_complete": settings_repo.is_setup_complete(),
    }


@router.put("/preferences")
async def put_preferences(req: PreferencesPatch):
    return {"preferences": settings_repo.update_preferences(req.preferences)}


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
@router.get("/secrets")
async def list_secrets():
    """Presence and a mask for every credential. Never a plaintext value."""
    return {"secrets": secrets_lib.status()}


@router.put("/secrets/{key}")
async def put_secret(key: str, req: SecretValue):
    if key not in secrets_lib.KNOWN_KEYS:
        raise HTTPException(status_code=400, detail=f"unknown credential {key!r}")
    if not req.value.strip():
        raise HTTPException(status_code=400, detail="value cannot be empty")
    backend = secrets_lib.set(key, req.value.strip())
    return {"key": key, "stored_in": backend, "masked": secrets_lib.mask(req.value.strip())}


@router.post("/secrets/{key}/reveal")
async def reveal_secret(key: str):
    """The single path that returns a plaintext credential. The UI confirms first."""
    if key not in secrets_lib.KNOWN_KEYS:
        raise HTTPException(status_code=400, detail=f"unknown credential {key!r}")
    value = secrets_lib.reveal(key)
    if not value:
        raise HTTPException(status_code=404, detail="that credential is not set")
    return {"key": key, "value": value}


@router.post("/secrets/{key}/test")
async def test_secret(key: str):
    """Verify one credential against its real service."""
    if key not in secrets_lib.KNOWN_KEYS:
        raise HTTPException(status_code=400, detail=f"unknown credential {key!r}")
    ok, detail = _test_credential(key)
    return {"key": key, "ok": ok, "detail": detail}


def _test_credential(key: str) -> tuple[bool, str]:
    value = secrets_lib.get(key)
    if not value:
        return False, "not set"

    if key == "ANTHROPIC_API_KEY":
        return backends._anthropic_key_probe(value)

    if key.startswith("APIFY_TOKEN"):
        try:
            import requests
            r = requests.get("https://api.apify.com/v2/users/me",
                             params={"token": value}, timeout=10)
        except Exception as exc:  # noqa: BLE001
            return False, f"could not reach Apify: {exc}"
        if r.status_code == 200:
            try:
                return True, f"signed in as {r.json()['data'].get('username', 'your account')}"
            except Exception:  # noqa: BLE001
                return True, "token valid"
        if r.status_code in (401, 403):
            return False, "Apify rejected that token"
        return False, f"Apify returned HTTP {r.status_code}"

    if key == "TELEGRAM_BOT_TOKEN":
        try:
            import requests
            r = requests.get(f"https://api.telegram.org/bot{value}/getMe", timeout=10)
        except Exception as exc:  # noqa: BLE001
            return False, f"could not reach Telegram: {exc}"
        if r.status_code == 200 and r.json().get("ok"):
            return True, f"connected to @{r.json()['result'].get('username', 'your bot')}"
        return False, "Telegram rejected that token"

    if key == "TELEGRAM_CHAT_ID":
        # A chat ID only means anything paired with the bot token, so test the pair by
        # actually sending something — a syntactic check would pass a wrong-but-numeric id.
        token = secrets_lib.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return False, "set the bot token first"
        try:
            import requests
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": value, "text": "✅ JobPilot test message."},
                timeout=10)
        except Exception as exc:  # noqa: BLE001
            return False, f"could not reach Telegram: {exc}"
        if r.status_code == 200:
            return True, "test message delivered — check your phone"
        return False, f"Telegram refused the message ({r.status_code})"

    if key == "DISCORD_WEBHOOK_URL":
        if "discord.com/api/webhooks/" not in value:
            return False, "that doesn't look like a Discord webhook URL"
        try:
            import requests
            r = requests.post(value, json={"content": "✅ JobPilot test message."},
                              timeout=10)
        except Exception as exc:  # noqa: BLE001
            return False, f"could not reach Discord: {exc}"
        return (r.status_code in (200, 204),
                "test message delivered" if r.status_code in (200, 204)
                else f"Discord returned HTTP {r.status_code}")

    if key == "GEMINI_API_KEY":
        return True, "stored (not verified — Gemini support is experimental)"

    if key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        return True, "stored (verified when you authenticate the channel scraper)"

    return True, "stored"


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
@router.get("/backends")
async def list_backends(deep: bool = False):
    """Available AI backends. `deep=true` actually verifies authentication."""
    return {
        "backends": backends.probe_all(deep=deep),
        "selected": backends.selected(),
        "environment": backends.environment(),
    }


@router.put("/backends")
async def choose_backend(req: BackendChoice):
    try:
        return {"engine": backends.select(req.backend)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- #
# Setup status — what the Job Hunt and Scheduler pages gate on
# --------------------------------------------------------------------------- #
@router.get("/setup/status")
async def setup_status():
    from core.db import is_sqlite, ping

    profile = profiles_repo.current()
    resume = resumes_repo.active()
    prefs = settings_repo.preferences()
    db_ok, db_detail = ping()

    try:
        backend = backends.probe(backends.selected())
        backend_ready, backend_detail = backend.found, backend.detail
        backend_label = backend.label
    except Exception as exc:  # noqa: BLE001
        backend_ready, backend_detail, backend_label = False, str(exc), "unknown"

    checks = {
        "database": {
            "ok": db_ok,
            "detail": ("SQLite" if is_sqlite() else "PostgreSQL") + f" — {db_detail}",
            "label": "Storage",
        },
        "backend": {
            "ok": backend_ready,
            "detail": backend_detail,
            "label": f"AI backend ({backend_label})",
        },
        "resume": {
            "ok": bool(resume and not resume["missing"]),
            "detail": (f"{resume['folder']}/{resume['filename']}"
                       if resume and not resume["missing"]
                       else "no resume uploaded"),
            "label": "Resume",
        },
        "profile": {
            "ok": bool(profile and profile.get("profile_verified")),
            "detail": ("confirmed" if profile and profile.get("profile_verified")
                       else "extracted but not confirmed" if profile
                       else "not built yet"),
            "label": "Profile",
        },
        "preferences": {
            "ok": bool(prefs.get("locations") and prefs.get("role_types")),
            "detail": ("set" if prefs.get("locations") and prefs.get("role_types")
                       else "locations and roles not set"),
            "label": "Job preferences",
        },
        "notifications": {
            "ok": bool(prefs.get("notify_channels")),
            "detail": (", ".join(prefs.get("notify_channels") or [])
                       or "none — results stay in the web UI"),
            "label": "Delivery",
            "optional": True,
        },
    }

    blocking = [k for k, v in checks.items() if not v["ok"] and not v.get("optional")]
    return {
        "ready": not blocking,
        "blocking": blocking,
        "checks": checks,
        "setup_complete": settings_repo.is_setup_complete(),
    }
