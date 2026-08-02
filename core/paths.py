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
    """Create the full data-directory tree and return its root."""
    root = jobpilot_dir()
    for sub in ("options", "cache", "reports", "runs", "resumes", "resumes/tailored", "logs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


# -- individual paths ------------------------------------------------------- #
def options_dir() -> Path:
    return jobpilot_dir() / "options"


def cache_dir() -> Path:
    return jobpilot_dir() / "cache"


def reports_dir() -> Path:
    return jobpilot_dir() / "reports"


def logs_dir() -> Path:
    return jobpilot_dir() / "logs"


def resumes_dir() -> Path:
    return jobpilot_dir() / "resumes"


def tailored_dir() -> Path:
    return resumes_dir() / "tailored"


def runs_root() -> Path:
    """Parent of all run-scoped artifact directories."""
    return jobpilot_dir() / "runs"


def run_dir(run_id: str) -> Path:
    return runs_root() / run_id


def prefs_path() -> Path:
    """Legacy preferences.json — still written as an export, no longer authoritative."""
    return options_dir() / "preferences.json"


def profile_path() -> Path:
    """Legacy profile.json — kept in sync for the Layer B skills that read it."""
    return cache_dir() / "profile.json"


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
