"""Single source of truth for JobPilot's on-disk layout.

Historically `jobpilot_dir()` was copy-pasted into ~8 modules (jp_secrets, record_scored,
report_generator, resume_tailor, telegram_notify, feedback, resume_parser, dedupe,
server/common). New code imports from here; the old copies stay for the standalone
Layer A scripts, which must keep working with zero imports beyond the stdlib.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DIR = "~/.claude/job-hunt-ai"


def jobpilot_dir() -> Path:
    """The data directory. Override with $JOBPILOT_DIR."""
    return Path(os.path.expanduser(os.environ.get("JOBPILOT_DIR", DEFAULT_DIR)))


def ensure_dirs() -> Path:
    """Create the full instance-wide data-directory tree and return its root.

    Only the genuinely shared subdirectories: DB config, logs, and the `users/` parent.
    Per-account trees are created on demand by `ensure_user_dirs()`.
    """
    root = jobpilot_dir()
    for sub in ("cache", "logs", "users"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


# -- individual paths (instance-wide) ---------------------------------------- #
def options_dir() -> Path:
    return jobpilot_dir() / "options"


def cache_dir() -> Path:
    return jobpilot_dir() / "cache"


def logs_dir() -> Path:
    return jobpilot_dir() / "logs"


def sqlite_path() -> Path:
    return cache_dir() / "jobpilot.db"


def legacy_sqlite_path() -> Path:
    """The v1 database (jobs_seen / score_cache / user_feedback / url_security_cache)."""
    return cache_dir() / "jobs.sqlite"


def db_config_path() -> Path:
    """Where the resolved database URL is cached between processes."""
    return cache_dir() / "database.json"


def migrated_marker() -> Path:
    return cache_dir() / ".v1_migrated"


# -- individual paths (per-account) ------------------------------------------ #
def user_dir(user_id: int) -> Path:
    """Root of one account's private tree: `<jobpilot_dir>/users/<user_id>/`."""
    return jobpilot_dir() / "users" / str(user_id)


def ensure_user_dirs(user_id: int) -> Path:
    """Create one account's data tree and return its root."""
    root = user_dir(user_id)
    for sub in ("options", "cache", "reports", "runs", "resumes", "resumes/tailored", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def reports_dir(user_id: int) -> Path:
    return user_dir(user_id) / "reports"


def resumes_dir(user_id: int) -> Path:
    return user_dir(user_id) / "resumes"


def tailored_dir(user_id: int) -> Path:
    return resumes_dir(user_id) / "tailored"


def runs_root(user_id: int) -> Path:
    """Parent of all run-scoped artifact directories for one account."""
    return user_dir(user_id) / "runs"


def run_dir(user_id: int, run_id: str) -> Path:
    return runs_root(user_id) / run_id


def prefs_path(user_id: int) -> Path:
    """Legacy preferences.json — still written as an export, no longer authoritative."""
    return user_dir(user_id) / "options" / "preferences.json"


def profile_path(user_id: int) -> Path:
    """Legacy profile.json — kept in sync for the Layer B skills that read it."""
    return user_dir(user_id) / "cache" / "profile.json"
