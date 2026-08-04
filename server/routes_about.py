"""About — what this install is, what it's running on, and what changed between versions.

Everything here is local: the version, the tools on PATH, the data directory and the
bundled CHANGELOG. The stats the About page charts come from the existing
`/api/jobs/stats` and `/api/cost/daily` endpoints — no numbers are duplicated here.
"""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from fastapi import APIRouter

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from core import backends, changelog, tailoring  # noqa: E402
from core.db import is_sqlite, resolve_url  # noqa: E402
from core.paths import jobpilot_dir  # noqa: E402
from core.version import app_version  # noqa: E402

router = APIRouter(prefix="/api/about", tags=["about"])

REPO_URL = "https://github.com/ashlesh-t/jobpilot"
ISSUES_URL = f"{REPO_URL}/issues/new"


def _install_source() -> str:
    """pipx | pip | local | checkout — the same rule `jobpilot upgrade` applies."""
    manager = "pipx" if "pipx" in Path(sys.prefix).parts else "pip"
    try:
        from importlib.metadata import Distribution
        raw = Distribution.from_name("jobpilot-ai").read_text("direct_url.json")
    except Exception:  # noqa: BLE001
        return "checkout"
    if raw:
        import json
        try:
            if "dir_info" in json.loads(raw):
                return "local"
        except ValueError:
            pass
    return manager


def _tools() -> list[dict]:
    """What JobPilot can and can't do on this machine right now."""
    rows: list[dict] = []

    try:
        # Public, pre-login page — no account in scope, so a backend that needs a
        # per-user API key (claude_api/gemini) will show as "not configured" here
        # even if some account on this instance has one set.
        info = backends.probe(backends.selected(), 0)
        rows.append({
            "name": "AI backend", "found": info.found, "detail": info.label,
            "required": True,
            "hint": "" if info.found else "run `jobpilot setup` to pick and sign in to one",
        })
    except Exception:  # noqa: BLE001
        rows.append({"name": "AI backend", "found": False, "detail": "not selected",
                     "required": True, "hint": "run `jobpilot setup`"})

    has_pdf = tailoring.has_tectonic()
    rows.append({
        "name": "PDF compiler (tectonic)", "found": has_pdf,
        "detail": "tailored resumes compile to PDF" if has_pdf
                  else "tailored resumes stay as LaTeX source",
        "required": False,
        "hint": "" if has_pdf else "  or  ".join(backends.tectonic_install_hints()),
    })

    docker = bool(shutil.which("docker"))
    rows.append({
        "name": "Docker", "found": docker,
        "detail": "available for the PostgreSQL container" if docker
                  else "not installed — SQLite is used instead",
        "required": False, "hint": "",
    })
    return rows


@router.get("")
async def about():
    return {
        "version": app_version(),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "install_source": _install_source(),
        "data_dir": str(jobpilot_dir()),
        "db_backend": "SQLite" if is_sqlite() else "PostgreSQL",
        "db_url": resolve_url().split("@")[-1],   # never expose a password
        "repo_url": REPO_URL,
        "issues_url": ISSUES_URL,
        "tools": _tools(),
    }


@router.get("/changelog")
async def release_notes():
    releases = changelog.load()
    current = app_version()
    return {
        "current": current,
        "releases": releases,
        "bundled": bool(releases),
        "newer": [r["version"] for r in releases
                  if changelog.is_newer(r["version"], current)],
    }
