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
from .base import EventCB, RunEngine, RunEvent, RunResult  # noqa: E402

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
        try:
            async for message in query(prompt=prompt, options=options):
                final_text = self._handle_message(message, on_event) or final_text
        except Exception as exc:  # noqa: BLE001
            on_event(RunEvent("done", "error", f"agent error: {exc}", origin="engine"))
            return RunResult(ok=False, error=str(exc))

        on_event(RunEvent("done", "done", "run complete", origin="engine",
                          data={"summary": final_text[:2000]}))
        return RunResult(ok=True, exit_code=0, artifacts={"final_text": final_text})

    # ------------------------------------------------------------------ #
    def _handle_message(self, message, on_event: EventCB) -> str | None:
        """Normalize an Agent SDK message into RunEvents. Returns final text if any."""
        cls = type(message).__name__

        if cls == "AssistantMessage":
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
            return str(getattr(message, "result", "") or "")

        return None


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
