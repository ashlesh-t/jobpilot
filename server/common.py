"""Shared paths + config helpers for the JobPilot service.

Centralizes sys.path wiring so `engines`, `scripts.notify`, `secrets`, and `run_events`
import cleanly from anywhere under server/. Also wraps preferences read/write (respecting
the repo rule: always read before write) and secrets via scripts/secrets.py.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_DIR / "scripts"

# Wire import paths once, for the whole server package.
for p in (str(REPO_DIR), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def prefs_path() -> Path:
    return jobpilot_dir() / "options" / "preferences.json"


def runs_dir() -> Path:
    d = jobpilot_dir() / "cache" / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def profile_path() -> Path:
    return jobpilot_dir() / "cache" / "profile.json"


def profile_review_done_path() -> Path:
    """Sentinel file signaling the user clicked Done in the profile review UI."""
    return jobpilot_dir() / "cache" / ".profile_review_done"


def load_prefs() -> dict:
    try:
        return json.loads(prefs_path().read_text())
    except Exception:
        # Fall back to the repo example so the UI has sane defaults on a fresh install.
        try:
            return json.loads((REPO_DIR / "config" / "preferences.example.json").read_text())
        except Exception:
            return {}


def save_prefs(prefs: dict) -> None:
    """Merge-write preferences.json (read-before-write per repo rule)."""
    current = {}
    p = prefs_path()
    if p.exists():
        try:
            current = json.loads(p.read_text())
        except Exception:
            current = {}
    current.update(prefs)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(current, indent=2, ensure_ascii=False))


def find_available_port(host: str, preferred: int, max_tries: int = 20) -> int:
    """Return `preferred` if free, else the next free port, else an OS-assigned one.

    Scans sequentially (preferred, preferred+1, …) first since a predictable neighbor
    is friendlier to bookmark than a random high port; only falls back to an
    OS-assigned port if the whole range is occupied.
    """
    for port in range(preferred, preferred + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def engine_config() -> dict:
    """The `engine` block from preferences, with defaults."""
    prefs = load_prefs()
    eng = prefs.get("engine") or {}
    return {
        "provider": eng.get("provider", "claude_code"),
        "model": eng.get("model", ""),
        "permission_mode": eng.get("permission_mode", "bypassPermissions"),
    }
