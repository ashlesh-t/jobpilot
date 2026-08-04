"""Run-scoped artifact storage.

Every run gets `<jobpilot_dir>/runs/<run_id>/` and every phase reads and writes named
JSON artifacts inside it. Two consequences that matter:

  * Two runs can never clobber each other (v1 shared `/tmp/jobpilot_*.json`).
  * Rerunning a phase months later still has its inputs on disk, which is what makes
    "rerun just the scoring phase" meaningful rather than a full re-scrape.

Artifacts stay on disk rather than in the database: they can reach tens of megabytes,
and the Layer A scripts read them as plain files. The database stores small summaries
(`phases.artifact`) plus the path.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

# Canonical artifact names. `jp_paths.artifact(name)` resolves the same names for the
# Layer A scripts, so both sides agree without passing paths around.
RAW = "raw"
SCRAPE_STATUS = "scrape_status"
DEDUPED = "deduped"
FILTERED = "filtered"
DISCOVERED = "discovered"
RELEVANT = "relevant"
SCORED = "scored"
NOTIFY_RECEIPT = "notify_receipt"

KNOWN = (RAW, SCRAPE_STATUS, DEDUPED, FILTERED, DISCOVERED, RELEVANT, SCORED,
         NOTIFY_RECEIPT)


def runs_root(user_id: int) -> Path:
    from core.paths import runs_root as _root
    return _root(user_id)


class ArtifactStore:
    """Filesystem access for one run's artifacts."""

    def __init__(self, user_id: int, run_id: str):
        self.user_id = user_id
        self.run_id = run_id
        self.dir = runs_root(user_id) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- paths ---------------------------------------------------------- #
    def path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def events_path(self) -> Path:
        """Where Layer A appends its stage events (scripts/run_events.py)."""
        return self.dir / "events.jsonl"

    def env(self) -> dict[str, str]:
        """Environment every phase subprocess inherits so it writes into this run.

        `JOBPILOT_USER_ID` is what makes `scripts/jp_secrets.py` and `scripts/feedback.py`
        resolve secrets and feedback rows for the right account.
        """
        return {
            "JOBPILOT_RUN_ID": self.run_id,
            "JOBPILOT_RUN_DIR": str(self.dir),
            "JOBPILOT_USER_ID": str(self.user_id),
        }

    # -- read / write --------------------------------------------------- #
    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def read(self, name: str, default: Any = None) -> Any:
        try:
            return json.loads(self.path(name).read_text())
        except Exception:
            return default

    def write(self, name: str, data: Any) -> Path:
        p = self.path(name)
        # Write via a temp file in the same directory so a crash mid-write can never
        # leave a half-parsed artifact that a rerun would silently trust.
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        os.replace(tmp, p)
        return p

    def count(self, name: str) -> int:
        data = self.read(name, [])
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return len(data)
        return 0

    def size(self, name: str) -> int:
        try:
            return self.path(name).stat().st_size
        except OSError:
            return 0

    def copy_from(self, other: "ArtifactStore", name: str) -> bool:
        """Seed this run's artifact from another run (used when resuming)."""
        src = other.path(name)
        if not src.exists():
            return False
        shutil.copy2(src, self.path(name))
        return True

    def inventory(self) -> list[dict]:
        """What this run produced — the "View artifact" list in the UI."""
        out = []
        for name in KNOWN:
            p = self.path(name)
            if not p.exists():
                continue
            out.append({
                "name": name,
                "path": str(p),
                "size": p.stat().st_size,
                "count": self.count(name),
            })
        return out

    def truncate_events(self) -> None:
        self.events_path().write_text("")

    def remove(self, name: str) -> None:
        self.path(name).unlink(missing_ok=True)

    def destroy(self) -> None:
        """Delete the whole run directory. Used when purging run history."""
        shutil.rmtree(self.dir, ignore_errors=True)


def latest_with(user_id: int, name: str, *, before: str | None = None) -> ArtifactStore | None:
    """Most recent run that has artifact `name` — how a fresh run reuses prior work."""
    root = runs_root(user_id)
    if not root.exists():
        return None
    for d in sorted((p for p in root.iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True):
        if before and d.name >= before:
            continue
        if (d / f"{name}.json").exists():
            return ArtifactStore(user_id, d.name)
    return None
