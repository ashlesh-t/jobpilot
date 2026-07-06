"""Run-event emitter — pure Python, NO LLM, zero external deps.

Provides a provider-neutral event stream for a single pipeline run so the UI can
render a live, harness-style timeline. Safe to import from Layer A scripts
(apify_scraper.py, dedupe.py, filter.py) because it does nothing unless a run is
active.

A run is "active" when the environment variable JOBPILOT_RUN_ID is set (the FastAPI
RunManager sets it before invoking Layer A / an engine). When it is unset — e.g. a
developer runs `python3 scripts/filter.py` by hand — every emit() is a cheap no-op,
so nothing about existing CLI behaviour changes.

Event record (one JSON object per line in events.jsonl):
    {
      "run_id": "<id>",
      "seq":    <monotonic int>,
      "ts":     "<ISO-8601 UTC>",
      "stage":  "scrape" | "dedupe" | "filter" | "relevance" | "score" |
                "salary" | "report" | "tailor" | "notify" | "done" | "log",
      "status": "started" | "progress" | "done" | "error",
      "msg":    "<human-readable one-liner>",
      "data":   { ... arbitrary structured payload ... }
    }

The same schema is emitted by Layer A scripts here and by the engine adapters
(engines/*.py), so a single SSE consumer handles both.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

# Canonical stage vocabulary — keep in sync with server/events.py CANONICAL_STAGES.
STAGES = (
    "scrape", "dedupe", "filter", "relevance", "score",
    "salary", "report", "tailor", "notify", "done", "log",
)

_lock = threading.Lock()
_seq = 0


def run_id() -> str | None:
    """The active run id, or None when no run is in progress (CLI use)."""
    rid = os.environ.get("JOBPILOT_RUN_ID", "").strip()
    return rid or None


def run_dir(rid: str | None = None) -> Path:
    """Scratch directory for a run's artifacts + event log."""
    rid = rid or run_id() or "adhoc"
    base = os.environ.get("JOBPILOT_RUN_DIR", "").strip()
    if base:
        return Path(base)
    return Path("/tmp") / f"jobpilot_run_{rid}"


def events_path(rid: str | None = None) -> Path:
    return run_dir(rid) / "events.jsonl"


def _next_seq() -> int:
    global _seq
    with _lock:
        _seq += 1
        return _seq


def emit(stage: str, status: str = "progress", msg: str = "", **data) -> None:
    """Append one event to the active run's events.jsonl. No-op when no run is active.

    Never raises — event logging must never break the pipeline.
    """
    rid = run_id()
    if not rid:
        return
    record = {
        "run_id": rid,
        "seq": _next_seq(),
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "stage": stage if stage in STAGES else "log",
        "status": status,
        "msg": msg,
        "data": data or {},
    }
    try:
        path = events_path(rid)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Best-effort: a full disk or race must not abort scraping.
        pass


def log(msg: str, **data) -> None:
    """Shorthand for a free-form log line (stage='log')."""
    emit("log", "progress", msg, **data)


if __name__ == "__main__":
    # Manual smoke test: JOBPILOT_RUN_ID=demo python3 scripts/run_events.py
    emit("scrape", "started", "demo scrape begins")
    emit("scrape", "progress", "internshala done", source="internshala", count=20)
    emit("scrape", "done", "scrape complete", total=42)
    rid = run_id() or "adhoc"
    print(f"wrote events for run {rid} -> {events_path()}")
