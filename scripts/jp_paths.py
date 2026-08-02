"""Run-scoped artifact paths for the Layer A scripts.

v1 hardcoded `/tmp/jobpilot_<name>.json`, so two runs on the same machine silently
overwrote each other's intermediate files. v2 gives every run its own directory and
passes it down through `$JOBPILOT_RUN_DIR`.

Both shapes are supported deliberately:
  * `$JOBPILOT_RUN_DIR` set   → `<run_dir>/<name>.json`   (the orchestrator's runs)
  * unset                     → `/tmp/jobpilot_<name>.json` (a bare CLI or plugin run)

Stdlib only — these scripts are Layer A and must never pull in the LLM stack.
"""
from __future__ import annotations

import os
from pathlib import Path

LEGACY_PREFIX = "/tmp/jobpilot_"


def run_dir() -> Path | None:
    """The active run's artifact directory, or None outside an orchestrated run."""
    raw = os.environ.get("JOBPILOT_RUN_DIR")
    if raw:
        return Path(os.path.expanduser(raw))
    rid = os.environ.get("JOBPILOT_RUN_ID")
    if rid:
        base = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
        return Path(os.path.expanduser(base)) / "runs" / rid
    return None


def artifact(name: str) -> str:
    """Absolute path for artifact `name` (e.g. "raw", "filtered", "scored")."""
    d = run_dir()
    if d is None:
        return f"{LEGACY_PREFIX}{name}.json"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{name}.json")


def scratch(name: str) -> str:
    """Non-JSON run-scoped scratch file (e.g. the tailoring counter)."""
    d = run_dir()
    if d is None:
        return f"{LEGACY_PREFIX}{name}"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / name)
