"""GeminiEngine — Google Gemini / Antigravity CLI adapter.

Shells out to the `gemini` (or `antigravity`) CLI in headless mode, the same shape as
engines/claude_code.py. The SKILL.md body is passed as the program so Layer B logic is
never duplicated per provider.

Marked experimental on purpose: the Gemini CLI's tool-use contract and output format
differ from Claude Code's, so tool narration is best-effort. Layer A stage counts still
come from events.jsonl and are exact regardless of provider — which is why a run on
Gemini still shows correct scrape/dedupe/filter numbers even if narration is thin.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from .base import (  # noqa: E402
    EventCB,
    RunEngine,
    RunEvent,
    RunResult,
    SUBPROCESS_STREAM_LIMIT,
    Usage,
)

REPO_DIR = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_DIR / "skills" / "job-search" / "SKILL.md"
CANDIDATE_CLIS = ("gemini", "antigravity")


class GeminiEngine(RunEngine):
    name = "gemini"
    label = "Google Gemini / Antigravity (experimental)"
    metered = True

    def __init__(self, model: str | None = None, cli: str | None = None):
        self.model = (model or "").strip()
        self.cli = cli or self._discover_cli()
        self.proc: asyncio.subprocess.Process | None = None
        self._usage = Usage(source="estimated")

    @staticmethod
    def _discover_cli() -> str | None:
        for name in CANDIDATE_CLIS:
            if shutil.which(name):
                return name
        return None

    # ------------------------------------------------------------------ #
    def available(self) -> tuple[bool, str]:
        if not self.cli:
            return False, ("no `gemini` or `antigravity` CLI on PATH — "
                           "install one, e.g. `npm install -g @google/gemini-cli`")
        from core import secrets
        # The CLI can be signed in interactively instead of using a key, so a missing
        # key is a warning path rather than a hard failure.
        if not secrets.get("GEMINI_API_KEY") and not shutil.which(self.cli):
            return False, "GEMINI_API_KEY not set and the CLI is not signed in"
        return True, ""

    def _program_text(self, program: str) -> str:
        try:
            body = SKILL_PATH.read_text(encoding="utf-8")
        except OSError:
            body = ""
        return (
            f"Run the JobPilot {program} pipeline now, end to end, fully autonomously. "
            "Execute its Layer A python scripts via shell commands and perform the "
            "Layer B reasoning yourself. Never ask questions; degrade gracefully on "
            "failures and always attempt the report and notify steps.\n\n" + body
        )

    # ------------------------------------------------------------------ #
    async def run(self, program: str, run_id: str, on_event: EventCB) -> RunResult:
        ok, reason = self.available()
        if not ok:
            on_event(RunEvent("done", "error", reason, origin="engine"))
            return RunResult(ok=False, error=reason)

        cmd = [self.cli, "--prompt", self._program_text(program), "--yolo"]
        if self.model:
            cmd += ["--model", self.model]

        env = dict(os.environ)
        env["JOBPILOT_RUN_ID"] = run_id
        from core import secrets
        key = secrets.get("GEMINI_API_KEY")
        if key:
            env.setdefault("GEMINI_API_KEY", key)

        on_event(RunEvent("log", "started", f"{self.cli} headless run", origin="engine"))
        self._usage = Usage(source="estimated", model=self.model)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(REPO_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=SUBPROCESS_STREAM_LIMIT,
            )
        except OSError as exc:
            msg = f"could not start {self.cli}: {exc}"
            on_event(RunEvent("done", "error", msg, origin="engine"))
            return RunResult(ok=False, error=msg)
        self.proc = proc

        final_text = ""
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if not line.strip():
                continue
            final_text = self._handle_line(line, on_event) or final_text

        stderr = b""
        if proc.stderr is not None:
            stderr = await proc.stderr.read()
        rc = await proc.wait()
        self.proc = None

        if rc != 0:
            if rc in (-15, 143, -9, 137):
                on_event(RunEvent("done", "error", "cancelled", origin="engine"))
                return RunResult(ok=False, exit_code=rc, error="cancelled", usage=self._usage)
            msg = stderr.decode("utf-8", "replace").strip()[:400] or f"exit {rc}"
            on_event(RunEvent("done", "error", f"{self.cli} exited {rc}: {msg}",
                              origin="engine"))
            return RunResult(ok=False, exit_code=rc, error=msg, usage=self._usage)

        on_event(RunEvent("done", "done", "run complete", origin="engine",
                          data={"summary": final_text[:2000]}))
        return RunResult(ok=True, exit_code=0, artifacts={"final_text": final_text},
                         usage=self._usage)

    # ------------------------------------------------------------------ #
    def _handle_line(self, line: str, on_event: EventCB) -> str | None:
        """Accept JSON-lines when the CLI emits them; fall back to plain-text logging."""
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                evt = json.loads(stripped)
            except json.JSONDecodeError:
                evt = None
            if isinstance(evt, dict):
                return self._handle_json(evt, on_event)
        on_event(RunEvent("log", "progress", stripped[:300], origin="engine"))
        return None

    def _handle_json(self, evt: dict, on_event: EventCB) -> str | None:
        kind = str(evt.get("type") or evt.get("kind") or "").lower()
        if "tool" in kind:
            name = evt.get("name") or evt.get("tool") or "?"
            self._emit_tool(on_event, str(name), evt.get("input") or evt.get("args"))
            return None
        usage = evt.get("usage") or evt.get("usageMetadata")
        if isinstance(usage, dict):
            self._usage.tokens_in += int(usage.get("promptTokenCount")
                                         or usage.get("input_tokens") or 0)
            self._usage.tokens_out += int(usage.get("candidatesTokenCount")
                                          or usage.get("output_tokens") or 0)
            self._usage.source = "metered"
        text = evt.get("text") or evt.get("response") or evt.get("result")
        if isinstance(text, str) and text.strip():
            on_event(RunEvent("log", "progress", text.strip()[:300], origin="engine",
                              data={"kind": "assistant_text"}))
            if kind in ("result", "final"):
                return text
        return None

    async def stop(self) -> None:
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
