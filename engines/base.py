"""RunEngine — provider adapter interface + shared helpers.

An engine executes the JobPilot `/job-search` *program* (Layer A python scripts +
Layer B reasoning) on some provider (Claude Code subscription, Anthropic API, Gemini…)
and reports progress by calling `on_event(RunEvent)`.

The design keeps two event sources cleanly separated:

  1. Authoritative stage counts (scrape / dedupe / filter, with per-source numbers)
     come from Layer A's `scripts/run_events.py` -> events.jsonl, tailed by the
     RunManager. Engines do NOT re-derive these.
  2. Layer B narration (which tool is running, and inferred Layer B stages like
     score / salary / report / tailor / notify) is emitted by the engine here, by
     mapping each provider tool-call to a canonical stage.

Both produce the SAME `RunEvent` shape, so the SSE consumer is uniform.

RunEngine is provider-neutral: it knows nothing about FastAPI. `on_event` is a plain
sync callback; the RunManager is responsible for fanning events out to SSE clients.
"""
from __future__ import annotations

import abc
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

# Keep in sync with scripts/run_events.STAGES and server/events.CANONICAL_STAGES.
CANONICAL_STAGES = (
    "scrape", "dedupe", "filter", "relevance", "score",
    "salary", "report", "tailor", "notify", "done", "log",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class RunEvent:
    """One normalized progress event. Mirrors the Layer A events.jsonl record."""
    stage: str
    status: str = "progress"          # started | progress | done | error
    msg: str = ""
    data: dict = field(default_factory=dict)
    origin: str = "engine"            # "engine" | "layerA" | "tool"
    ts: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.stage not in CANONICAL_STAGES:
            d["stage"] = "log"
        return d


@dataclass
class RunResult:
    ok: bool
    exit_code: int | None = None
    error: str = ""
    artifacts: dict = field(default_factory=dict)


EventCB = Callable[[RunEvent], None]


# --------------------------------------------------------------------------- #
# Tool-call -> canonical stage mapping (heuristic Layer B narration)
# --------------------------------------------------------------------------- #
def map_tool_to_stage(tool_name: str, tool_input: dict | None) -> str | None:
    """Infer which pipeline stage a provider tool-call represents.

    Authoritative counts still come from events.jsonl; this is for live narration of
    the Layer B steps the LLM performs (which are not python scripts).
    """
    t = (tool_name or "").lower()
    blob = ""
    try:
        blob = json.dumps(tool_input or {}).lower()
    except Exception:
        blob = str(tool_input).lower()

    if "telegram_notify" in blob or "notify/" in blob:
        return "notify"
    if "report_generator" in blob:
        return "report"
    if "tectonic" in blob or "resume_tailor" in blob or "/tailored/" in blob:
        return "tailor"
    if "apify_scraper" in blob:
        return "scrape"
    if "dedupe.py" in blob:
        return "dedupe"
    if "filter.py" in blob:
        return "filter"
    if t == "websearch":
        return "salary"       # Layer B salary research uses WebSearch
    if t == "webfetch":
        return "score"        # JD enrichment before scoring
    return None


class RunEngine(abc.ABC):
    """Base class for all provider engines."""

    #: stable identifier used in config + API ("claude_code" | "claude_api" | "gemini")
    name: str = "base"
    #: human label for the setup UI
    label: str = "Base"
    #: whether the engine bills per token (drives the UI cost hint)
    metered: bool = False

    @abc.abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return (usable_on_this_machine, reason_if_not)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def run(self, program: str, run_id: str, on_event: EventCB) -> RunResult:
        """Execute `program` (e.g. "/job-search"), calling on_event as it progresses."""
        raise NotImplementedError

    # -- shared helper: emit a tool-call as narration + inferred stage -------- #
    def _emit_tool(self, on_event: EventCB, tool_name: str, tool_input: dict | None) -> None:
        stage = map_tool_to_stage(tool_name, tool_input)
        summary = self._tool_summary(tool_name, tool_input)
        on_event(RunEvent(stage="log", status="progress",
                          msg=summary, origin="tool",
                          data={"tool": tool_name}))
        if stage:
            on_event(RunEvent(stage=stage, status="started",
                              msg=summary, origin="engine",
                              data={"tool": tool_name}))

    @staticmethod
    def _tool_summary(tool_name: str, tool_input: dict | None) -> str:
        ti = tool_input or {}
        if tool_name == "Bash":
            return f"$ {str(ti.get('command', ''))[:120]}"
        if tool_name in ("WebSearch",):
            return f"search: {ti.get('query', '')}"
        if tool_name in ("WebFetch",):
            return f"fetch: {ti.get('url', '')}"
        if tool_name in ("Write", "Edit"):
            return f"{tool_name}: {ti.get('file_path', '')}"
        if tool_name == "Read":
            return f"read: {ti.get('file_path', '')}"
        return tool_name
