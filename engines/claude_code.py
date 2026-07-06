"""ClaudeCodeEngine — run /job-search under a Claude Pro/Max subscription.

Shells out to the Claude Code CLI in headless mode:

    claude -p "/job-search" --output-format stream-json --verbose --permission-mode <mode>

This reuses `skills/job-search/SKILL.md` verbatim as the program, runs under the user's
subscription (no API key, no per-token cost), and emits a structured JSON event stream we
normalize into RunEvents. GUI automation of Claude Desktop is deliberately avoided.

Requires the `claude` CLI installed and logged in. `available()` verifies both.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .base import EventCB, RunEngine, RunEvent, RunResult  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent


class ClaudeCodeEngine(RunEngine):
    name = "claude_code"
    label = "Claude Code (Pro/Max subscription)"
    metered = False

    def __init__(self, permission_mode: str | None = None, cli: str = "claude"):
        # acceptEdits works with the repo allowlist; a headless scheduler may prefer
        # "bypassPermissions" for zero prompts. Configurable via arg or env.
        self.permission_mode = (
            permission_mode
            or os.environ.get("JOBPILOT_CLAUDE_PERMISSION_MODE")
            or "acceptEdits"
        )
        self.cli = cli

    # ------------------------------------------------------------------ #
    def available(self) -> tuple[bool, str]:
        exe = shutil.which(self.cli)
        if not exe:
            return False, f"`{self.cli}` CLI not found on PATH — install Claude Code"
        try:
            out = subprocess.run([self.cli, "--version"], capture_output=True,
                                 text=True, timeout=10)
            if out.returncode != 0:
                return False, f"`{self.cli} --version` failed: {out.stderr.strip()[:120]}"
        except Exception as exc:  # noqa: BLE001
            return False, f"`{self.cli}` not runnable: {exc}"
        return True, ""

    # ------------------------------------------------------------------ #
    async def run(self, program: str, run_id: str, on_event: EventCB) -> RunResult:
        ok, reason = self.available()
        if not ok:
            on_event(RunEvent("done", "error", reason, origin="engine"))
            return RunResult(ok=False, error=reason)

        cmd = [
            self.cli, "-p", program,
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", self.permission_mode,
        ]
        env = dict(os.environ)
        env["JOBPILOT_RUN_ID"] = run_id

        on_event(RunEvent("log", "started", f"claude -p {program} [{self.permission_mode}]",
                          origin="engine"))

        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(REPO_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        final_text = ""
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            final_text = self._handle_line(line, on_event) or final_text

        stderr = b""
        if proc.stderr is not None:
            stderr = await proc.stderr.read()
        rc = await proc.wait()

        if rc != 0:
            msg = stderr.decode("utf-8", "replace").strip()[:400] or f"exit {rc}"
            on_event(RunEvent("done", "error", f"claude exited {rc}: {msg}", origin="engine"))
            return RunResult(ok=False, exit_code=rc, error=msg)

        on_event(RunEvent("done", "done", "run complete", origin="engine",
                          data={"summary": final_text[:2000]}))
        return RunResult(ok=True, exit_code=0, artifacts={"final_text": final_text})

    # ------------------------------------------------------------------ #
    def _handle_line(self, line: str, on_event: EventCB) -> str | None:
        """Parse one stream-json line; emit tool narration. Returns final text if any."""
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            return None
        etype = evt.get("type")

        if etype == "assistant":
            for block in (evt.get("message", {}) or {}).get("content", []) or []:
                if block.get("type") == "tool_use":
                    self._emit_tool(on_event, block.get("name", "?"), block.get("input"))
                elif block.get("type") == "text" and block.get("text", "").strip():
                    on_event(RunEvent("log", "progress", block["text"].strip()[:300],
                                      origin="engine", data={"kind": "assistant_text"}))
            return None

        if etype == "result":
            return str(evt.get("result", "") or "")

        if etype == "system" and evt.get("subtype") == "init":
            on_event(RunEvent("log", "progress", "session initialized", origin="engine",
                              data={"session_id": evt.get("session_id", "")}))
        return None


# CLI smoke test: python -m engines.claude_code "/job-search"
if __name__ == "__main__":
    prog = sys.argv[1] if len(sys.argv) > 1 else "/job-search"
    eng = ClaudeCodeEngine()
    ok, why = eng.available()
    print(f"available: {ok} {why}", file=sys.stderr)
    if not ok:
        sys.exit(1)

    def _print(ev: RunEvent):
        print(f"[{ev.stage}/{ev.status}] {ev.msg}", file=sys.stderr)

    res = asyncio.run(eng.run(prog, "cli-smoke", _print))
    print(f"result ok={res.ok} exit={res.exit_code}", file=sys.stderr)
