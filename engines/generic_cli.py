"""GenericCliEngine — run any headless agent CLI from a command template.

Configured in Settings as `engine.command_template`, e.g.

    mytool run --yes --prompt {prompt}
    codex exec --full-auto {prompt}

`{prompt}` is substituted with the program text; `{program}` gives just the slash command
and `{run_id}` the run identifier. Output is parsed as JSON-lines when it looks like JSON
and logged verbatim otherwise.

Experimental by nature: JobPilot cannot know another tool's event schema, so tool-level
narration is best-effort. Layer A stage counts are unaffected — they come from
events.jsonl and stay exact on any backend.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
from pathlib import Path

from .base import EventCB, RunEngine, RunEvent, RunResult, Usage

REPO_DIR = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_DIR / "skills" / "job-search" / "SKILL.md"


class GenericCliEngine(RunEngine):
    name = "generic_cli"
    label = "Custom agent CLI (experimental)"
    metered = False

    def __init__(self, command_template: str | None = None, **_ignored):
        self.command_template = (command_template or self._configured_template()).strip()
        self.proc: asyncio.subprocess.Process | None = None
        self._usage = Usage(source="estimated")

    @staticmethod
    def _configured_template() -> str:
        try:
            from core.repo import settings as settings_repo
            return settings_repo.engine_config().get("command_template", "") or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    def available(self) -> tuple[bool, str]:
        if not self.command_template:
            return False, ("no command template configured — set engine.command_template, "
                           "e.g. `mytool run --prompt {prompt}`")
        if "{prompt}" not in self.command_template:
            return False, "command template must contain the {prompt} placeholder"
        try:
            binary = shlex.split(self.command_template)[0]
        except ValueError as exc:
            return False, f"command template is not parseable: {exc}"
        if shutil.which(binary) is None:
            return False, f"`{binary}` not found on PATH"
        return True, ""

    def _program_text(self, program: str) -> str:
        try:
            body = SKILL_PATH.read_text(encoding="utf-8")
        except OSError:
            body = ""
        return (
            f"Run the JobPilot {program} pipeline now, end to end, fully autonomously. "
            "Execute its Layer A python scripts via shell commands and perform the "
            "Layer B reasoning yourself. Never ask questions.\n\n" + body
        )

    def build_command(self, program: str, run_id: str) -> list[str]:
        """Substitute placeholders *after* splitting, so a prompt containing quotes or
        spaces can never inject extra shell words."""
        prompt = self._program_text(program)
        parts = shlex.split(self.command_template)
        return [
            p.replace("{prompt}", prompt).replace("{program}", program).replace("{run_id}", run_id)
            for p in parts
        ]

    # ------------------------------------------------------------------ #
    async def run(self, program: str, run_id: str, on_event: EventCB) -> RunResult:
        ok, reason = self.available()
        if not ok:
            on_event(RunEvent("done", "error", reason, origin="engine"))
            return RunResult(ok=False, error=reason)

        cmd = self.build_command(program, run_id)
        env = dict(os.environ)
        env["JOBPILOT_RUN_ID"] = run_id

        on_event(RunEvent("log", "started", f"$ {cmd[0]} … (custom backend)", origin="engine"))
        self._usage = Usage(source="estimated")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(REPO_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            msg = f"could not start {cmd[0]}: {exc}"
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
            on_event(RunEvent("done", "error", f"{cmd[0]} exited {rc}: {msg}", origin="engine"))
            return RunResult(ok=False, exit_code=rc, error=msg, usage=self._usage)

        on_event(RunEvent("done", "done", "run complete", origin="engine",
                          data={"summary": final_text[:2000]}))
        return RunResult(ok=True, exit_code=0, artifacts={"final_text": final_text},
                         usage=self._usage)

    def _handle_line(self, line: str, on_event: EventCB) -> str | None:
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                evt = json.loads(stripped)
            except json.JSONDecodeError:
                evt = None
            if isinstance(evt, dict):
                name = evt.get("tool") or evt.get("name")
                if name and "tool" in str(evt.get("type", "tool")).lower():
                    self._emit_tool(on_event, str(name), evt.get("input") or evt.get("args"))
                    return None
                text = evt.get("text") or evt.get("result") or evt.get("message")
                if isinstance(text, str) and text.strip():
                    on_event(RunEvent("log", "progress", text.strip()[:300], origin="engine"))
                    return text
                return None
        on_event(RunEvent("log", "progress", stripped[:300], origin="engine"))
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
