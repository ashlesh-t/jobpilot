"""ClaudeApiEngine — run /job-search via the Claude Agent SDK (metered API).

Uses `claude-agent-sdk` to drive the same program as the subscription engine, but billed
per token against ANTHROPIC_API_KEY. Layer B *logic* is not duplicated: the body of
`skills/job-search/SKILL.md` is loaded at runtime as the system prompt, so SKILL.md stays
the single source of truth for both Claude engines.

Tools granted match the surface SKILL.md assumes (Bash for the Layer A scripts, Read/Write
for reports + resumes, WebSearch/WebFetch for salary + JD enrichment).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from .base import EventCB, RunEngine, RunEvent, RunResult, Usage  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_DIR / "skills" / "job-search" / "SKILL.md"

ALLOWED_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]


class ClaudeApiEngine(RunEngine):
    name = "claude_api"
    label = "Anthropic API (metered)"
    metered = True

    def __init__(self, model: str | None = None, permission_mode: str = "acceptEdits"):
        # Empty → let the Agent SDK pick its default model. Set an explicit id in
        # preferences.engine.model only if you want to pin one; passing an invalid
        # id would otherwise break every run.
        self.model = (model or "").strip()
        self.permission_mode = permission_mode
        self._usage = Usage(source="metered")
        self._cancelled = False

    # ------------------------------------------------------------------ #
    def available(self) -> tuple[bool, str]:
        try:
            import claude_agent_sdk  # noqa: F401
        except Exception:
            return False, "claude-agent-sdk not installed (pip install claude-agent-sdk)"
        try:
            from jp_secrets import get_secret_optional  # noqa
        except Exception:
            return False, "secrets loader unavailable"
        if not get_secret_optional("ANTHROPIC_API_KEY"):
            return False, "ANTHROPIC_API_KEY not set"
        return True, ""

    def _system_prompt(self) -> str:
        try:
            body = SKILL_PATH.read_text(encoding="utf-8")
        except Exception:
            body = "Run the JobPilot /job-search pipeline."
        return (
            "You are JobPilot's autonomous /job-search engine. Execute the pipeline "
            "described below exactly, running its Layer A python scripts via Bash and "
            "performing Layer B reasoning yourself. Do not ask questions; run fully "
            "autonomously and degrade gracefully on failures.\n\n" + body
        )

    # ------------------------------------------------------------------ #
    async def run(self, program: str, run_id: str, on_event: EventCB) -> RunResult:
        ok, reason = self.available()
        if not ok:
            on_event(RunEvent("done", "error", reason, origin="engine"))
            return RunResult(ok=False, error=reason)

        import os
        os.environ["JOBPILOT_RUN_ID"] = run_id
        # Make the API key visible to the SDK from the secrets store.
        from jp_secrets import get_secret_optional  # noqa
        key = get_secret_optional("ANTHROPIC_API_KEY")
        if key:
            os.environ.setdefault("ANTHROPIC_API_KEY", key)

        from claude_agent_sdk import ClaudeAgentOptions, query  # noqa

        opt_kwargs = dict(
            system_prompt=self._system_prompt(),
            allowed_tools=ALLOWED_TOOLS,
            permission_mode=self.permission_mode,
            cwd=str(REPO_DIR),
        )
        if self.model:                       # only pin a model if explicitly configured
            opt_kwargs["model"] = self.model
        options = ClaudeAgentOptions(**opt_kwargs)
        prompt = (
            f"Run the {program} pipeline now, end to end, for the configured user. "
            "Follow the system prompt's steps exactly."
        )

        on_event(RunEvent("log", "started",
                          f"agent-sdk model={self.model or 'sdk-default'}", origin="engine"))
        final_text = ""
        self._usage = Usage(source="metered", model=self.model)
        self._cancelled = False
        try:
            async for message in query(prompt=prompt, options=options):
                if self._cancelled:
                    break
                final_text = self._handle_message(message, on_event) or final_text
        except Exception as exc:  # noqa: BLE001
            on_event(RunEvent("done", "error", f"agent error: {exc}", origin="engine"))
            return RunResult(ok=False, error=str(exc), usage=self._usage)

        if self._cancelled:
            on_event(RunEvent("done", "error", "cancelled", origin="engine"))
            return RunResult(ok=False, error="cancelled", usage=self._usage)

        on_event(RunEvent("done", "done", "run complete", origin="engine",
                          data={"summary": final_text[:2000]}))
        return RunResult(ok=True, exit_code=0, artifacts={"final_text": final_text},
                         usage=self._usage)

    async def stop(self) -> None:
        """Ask the message loop to break at the next yield.

        The SDK has no hard-kill hook, so cancellation lands on a message boundary
        rather than instantly — the orchestrator reports it as such.
        """
        self._cancelled = True

    # ------------------------------------------------------------------ #
    def _handle_message(self, message, on_event: EventCB) -> str | None:
        """Normalize an Agent SDK message into RunEvents. Returns final text if any."""
        cls = type(message).__name__

        if cls == "AssistantMessage":
            self._absorb_usage(getattr(message, "usage", None),
                               getattr(message, "model", ""))
            for block in getattr(message, "content", []) or []:
                bcls = type(block).__name__
                if bcls == "ToolUseBlock":
                    self._emit_tool(on_event, getattr(block, "name", "?"),
                                    getattr(block, "input", {}))
                elif bcls == "TextBlock":
                    txt = (getattr(block, "text", "") or "").strip()
                    if txt:
                        on_event(RunEvent("log", "progress", txt[:300], origin="engine",
                                          data={"kind": "assistant_text"}))
            return None

        if cls == "ResultMessage":
            self._absorb_usage(getattr(message, "usage", None), getattr(message, "model", ""))
            cost = getattr(message, "total_cost_usd", None)
            if isinstance(cost, (int, float)):
                self._usage.usd = float(cost)
            return str(getattr(message, "result", "") or "")

        return None

    def _absorb_usage(self, usage, model: str = "") -> None:
        """Accept either a dict or an SDK usage object — the shape varies by version."""
        if usage is None:
            return
        get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
        self._usage.tokens_in += int(get("input_tokens", 0) or 0)
        self._usage.tokens_out += int(get("output_tokens", 0) or 0)
        self._usage.cache_read += int(get("cache_read_input_tokens", 0) or 0)
        self._usage.cache_write += int(get("cache_creation_input_tokens", 0) or 0)
        if model:
            self._usage.model = model


# CLI smoke test: python -m engines.claude_api "/job-search"
if __name__ == "__main__":
    import asyncio
    prog = sys.argv[1] if len(sys.argv) > 1 else "/job-search"
    eng = ClaudeApiEngine()
    ok, why = eng.available()
    print(f"available: {ok} {why}", file=sys.stderr)
    if not ok:
        sys.exit(1)

    def _print(ev: RunEvent):
        print(f"[{ev.stage}/{ev.status}] {ev.msg}", file=sys.stderr)

    res = asyncio.run(eng.run(prog, "cli-smoke", _print))
    print(f"result ok={res.ok}", file=sys.stderr)
