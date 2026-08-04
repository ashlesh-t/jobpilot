"""ClaudeCodeEngine — run /job-search under a Claude Pro/Max subscription.

Shells out to the Claude Code CLI in headless mode:

    claude -p "/job-search" --output-format stream-json --verbose --permission-mode <mode>

This reuses `skills/job-search/SKILL.md` verbatim as the program, runs under the user's
subscription (no API key, no per-token cost), and emits a structured JSON event stream we
normalize into RunEvents. GUI automation of Claude Desktop is deliberately avoided.

Requires the `claude` CLI installed and logged in. `available()` checks the install
cheaply — it deliberately does NOT verify login, because the only reliable login probe
costs a full round trip. `core.backends.probe("claude_code", deep=True)` does that, and
is what Setup and Doctor call.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .base import (  # noqa: E402
    EventCB,
    RunEngine,
    RunEvent,
    RunResult,
    SUBPROCESS_STREAM_LIMIT,
    Usage,
)

REPO_DIR = Path(__file__).resolve().parent.parent


class ClaudeCodeEngine(RunEngine):
    name = "claude_code"
    label = "Claude Code (Pro/Max subscription)"
    metered = False

    def __init__(self, permission_mode: str | None = None, cli: str = "claude",
                model: str | None = None, **_ignored):
        # **_ignored absorbs `user_id` — the dispatch-uniform kwarg every engine
        # constructor accepts from engines.get_engine(), even though a subscription
        # login has no per-user secret to look up.
        # Every phase runs headless (`claude -p`, no terminal, no human) and every
        # skill's autonomy contract already forbids asking questions or blocking — so a
        # permission prompt here can never be answered anyway. "acceptEdits" only covers
        # file edits, leaving WebFetch/WebSearch/Bash to hang on an unanswerable prompt
        # (e.g. the discover phase's career-page fetches). bypassPermissions is the
        # correct default for this fully-unattended execution model, not a workaround.
        self.permission_mode = (
            permission_mode
            or os.environ.get("JOBPILOT_CLAUDE_PERMISSION_MODE")
            or "bypassPermissions"
        )
        self.cli = cli
        # An alias ("haiku"/"sonnet"/"opus") or a full model id — see core.model_catalog,
        # which resolves each phase's tier to one of these before the engine is built.
        self.model = (model or "").strip()
        self.proc: asyncio.subprocess.Process | None = None
        self._usage = Usage(source="subscription")

    # ------------------------------------------------------------------ #
    def available(self) -> tuple[bool, str]:
        """Install check only — see the module docstring on why login isn't probed here."""
        exe = shutil.which(self.cli)
        if not exe:
            return False, f"`{self.cli}` CLI not found on PATH — install Claude Code"
        try:
            # Pin cwd explicitly rather than inheriting the calling process's ambient
            # one: if this service was reinstalled/upgraded while still running, its
            # own working directory can be a now-deleted path, and a child spawned
            # into a deleted cwd fails with a confusing, runtime-specific error
            # (observed: Bun's own mangled "ENOENT ... ENOENT" for the `claude` CLI)
            # instead of a clear one.
            out = subprocess.run([self.cli, "--version"], capture_output=True,
                                 text=True, timeout=10, cwd=str(REPO_DIR))
            if out.returncode != 0:
                return False, f"`{self.cli} --version` failed: {out.stderr.strip()[:120]}"
        except FileNotFoundError as exc:
            if str(REPO_DIR) in str(exc):
                return False, (
                    f"this service's own install directory is gone ({REPO_DIR}) — it "
                    "was probably reinstalled/upgraded while still running. Restart "
                    "it: `jobpilot stop && jobpilot start`"
                )
            return False, f"`{self.cli}` not runnable: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"`{self.cli}` not runnable: {exc}"
        return True, ""

    def authenticated(self) -> tuple[bool, str]:
        """Deep login check, delegated to core.backends (one implementation, not two)."""
        from core import backends
        # claude_code's probe never reads a per-user secret (it's a machine-wide CLI
        # login check), so the user_id it's required to accept for dispatch uniformity
        # is unused here.
        info = backends.probe("claude_code", 0, deep=True)
        return info.authenticated, info.detail

    # ------------------------------------------------------------------ #
    async def run(self, program: str, run_id: str, on_event: EventCB) -> RunResult:
        ok, reason = self.available()
        if not ok:
            on_event(RunEvent("done", "error", reason, origin="engine"))
            return RunResult(ok=False, error=reason)

        # The data dir (profile, preferences, and every run's artifacts) lives outside
        # REPO_DIR — for a pip/pipx install it's under site-packages, the data dir is
        # under the user's home. Claude Code only trusts the cwd by default, so without
        # --add-dir every phase fails to read/write filtered.json, preferences.json,
        # discovered.json, etc. with a sandbox/file-access error.
        from core.paths import jobpilot_dir

        cmd = [
            self.cli, "-p", program,
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", self.permission_mode,
            "--add-dir", str(jobpilot_dir()),
        ]
        if self.model:
            cmd += ["--model", self.model]
        env = dict(os.environ)
        env["JOBPILOT_RUN_ID"] = run_id

        on_event(RunEvent("log", "started", f"claude -p {program} [{self.permission_mode}]",
                          origin="engine"))

        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(REPO_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=SUBPROCESS_STREAM_LIMIT,
        )
        # Kept on the instance so the orchestrator's stop() can reach it — in v1 the
        # handle only existed in this local scope, which made cancellation impossible.
        self.proc = proc

        final_text = ""
        self._usage = Usage(source="subscription", model=self.model)
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
        self.proc = None

        if rc != 0:
            msg = stderr.decode("utf-8", "replace").strip()[:400] or f"exit {rc}"
            # A terminated process (stop button) exits non-zero; that's a cancel, not a fault.
            if rc in (-15, 143, -9, 137):
                on_event(RunEvent("done", "error", "cancelled", origin="engine"))
                return RunResult(ok=False, exit_code=rc, error="cancelled",
                                 usage=self._usage)
            on_event(RunEvent("done", "error", f"claude exited {rc}: {msg}", origin="engine"))
            return RunResult(ok=False, exit_code=rc, error=msg, usage=self._usage)

        on_event(RunEvent("done", "done", "run complete", origin="engine",
                          data={"summary": final_text[:2000]}))
        return RunResult(ok=True, exit_code=0, artifacts={"final_text": final_text},
                         usage=self._usage)

    # ------------------------------------------------------------------ #
    def _handle_line(self, line: str, on_event: EventCB) -> str | None:
        """Parse one stream-json line; emit tool narration. Returns final text if any."""
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            return None
        etype = evt.get("type")

        if etype == "assistant":
            msg = evt.get("message", {}) or {}
            self._absorb_usage(msg.get("usage"), msg.get("model", ""))
            for block in msg.get("content", []) or []:
                if block.get("type") == "tool_use":
                    self._emit_tool(on_event, block.get("name", "?"), block.get("input"))
                elif block.get("type") == "text" and block.get("text", "").strip():
                    on_event(RunEvent("log", "progress", block["text"].strip()[:300],
                                      origin="engine", data={"kind": "assistant_text"}))
            return None

        if etype == "result":
            self._absorb_usage(evt.get("usage"), evt.get("model", ""))
            # The CLI reports total_cost_usd even on a subscription; keep it as a
            # reference figure but leave `source` as subscription so the meter is honest.
            cost = evt.get("total_cost_usd")
            if isinstance(cost, (int, float)):
                self._usage.usd = float(cost)
            return str(evt.get("result", "") or "")

        if etype == "system" and evt.get("subtype") == "init":
            on_event(RunEvent("log", "progress", "session initialized", origin="engine",
                              data={"session_id": evt.get("session_id", "")}))
        return None

    def _absorb_usage(self, usage: dict | None, model: str = "") -> None:
        if not isinstance(usage, dict):
            return
        u = getattr(self, "_usage", None) or Usage(source="subscription")
        u.tokens_in += int(usage.get("input_tokens") or 0)
        u.tokens_out += int(usage.get("output_tokens") or 0)
        u.cache_read += int(usage.get("cache_read_input_tokens") or 0)
        u.cache_write += int(usage.get("cache_creation_input_tokens") or 0)
        if model:
            u.model = model
        self._usage = u

    async def stop(self) -> None:
        """Terminate the running CLI. Graceful first, then hard after a grace period."""
        proc = getattr(self, "proc", None)
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()


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
