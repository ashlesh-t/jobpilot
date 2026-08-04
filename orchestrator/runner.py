"""The run executor — phase by phase, with stop, resume and per-phase rerun.

What v1 could not do and this can:

  * **Stop.** The subprocess handle (or the engine's cancel hook) is held on the running
    phase, so a stop actually reaches the child instead of orphaning it.
  * **Resume.** Completed phases and their artifacts are on disk and in the database, so
    resuming restarts at the first incomplete phase rather than re-scraping everything.
  * **Rerun one phase.** Rerunning invalidates that phase and everything downstream,
    because a fresh scoring pass makes the old salary research and report stale.
  * **Survive a restart.** Every event is persisted, so a finished run's timeline is
    still replayable after the service is restarted.

One run is active at a time. For a single-user local tool that is the correct, and
predictable, behaviour.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path

from . import phases as P
from .artifacts import ArtifactStore

REPO_DIR = Path(__file__).resolve().parent.parent

# A phase failing for one of these reasons is worth retrying; anything else is a real
# fault and retrying it just burns time and tokens.
TRANSIENT_MARKERS = (
    "timeout", "timed out", "temporarily", "connection", "network", "unreachable",
    "rate limit", "429", "500 ", "502", "503", "504", "overloaded", "econnreset",
)


class RunBusyError(Exception):
    """A run was requested while another is already active."""


class UnknownRunError(Exception):
    """The requested run id doesn't exist."""


def _is_transient(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in TRANSIENT_MARKERS)


class _ActiveRun:
    """Everything the orchestrator needs about the run currently executing."""

    def __init__(self, run_id: str, mode: str, engine_name: str, keys: list[str]):
        self.id = run_id
        self.mode = mode
        self.engine_name = engine_name
        self.keys = keys
        self.store = ArtifactStore(run_id)
        self.subscribers: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.engine = None
        self.current_phase: str = ""
        self.cancelled = False
        self.done_keys: list[str] = []


class Orchestrator:
    def __init__(self):
        self.active: _ActiveRun | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self, *, mode: str = "auto", engine: str | None = None,
                    only: list[str] | None = None, skip: list[str] | None = None,
                    trigger: str = "manual", slot_name: str = "") -> dict:
        from core.repo import runs as runs_repo
        from core.repo import settings as settings_repo

        async with self._lock:
            if self.active is not None:
                raise RunBusyError(f"run {self.active.id} is already in progress")

            engine_name = engine or settings_repo.engine_config()["provider"]
            keys = P.selection(only, skip)
            run_id = runs_repo.new_run_id()
            runs_repo.create(run_id, mode=mode, engine=engine_name, phase_keys=keys,
                             trigger=trigger, slot_name=slot_name)

            run = _ActiveRun(run_id, mode, engine_name, keys)
            run.store.truncate_events()
            self.active = run

        run.task = asyncio.create_task(self._execute(run))
        return runs_repo.get(run_id)

    async def resume(self, run_id: str) -> dict:
        """Continue a stopped or failed run from its first incomplete phase."""
        from core.repo import runs as runs_repo

        record = runs_repo.get(run_id)
        if record is None:
            raise UnknownRunError(run_id)

        async with self._lock:
            if self.active is not None:
                raise RunBusyError(f"run {self.active.id} is already in progress")
            pending = [p["key"] for p in record["phases"]
                       if p["status"] not in ("done", "skipped")]
            if not pending:
                return record
            run = _ActiveRun(run_id, record["mode"], record["engine"],
                             [p["key"] for p in record["phases"]])
            run.done_keys = [p["key"] for p in record["phases"] if p["status"] == "done"]
            self.active = run

        runs_repo.set_status(run_id, "running", error="")
        self._emit(run, "log", "started",
                   f"resuming from '{pending[0]}' — {len(run.done_keys)} phases already done")
        run.task = asyncio.create_task(self._execute(run))
        return runs_repo.get(run_id)

    async def rerun(self, run_id: str, phase_key: str) -> dict:
        """Reset `phase_key` and everything downstream, then run from there."""
        from core.repo import runs as runs_repo

        record = runs_repo.get(run_id)
        if record is None:
            raise UnknownRunError(run_id)
        P.get(phase_key)  # validates

        async with self._lock:
            if self.active is not None:
                raise RunBusyError(f"run {self.active.id} is already in progress")
            reset = runs_repo.invalidate_from(run_id, phase_key)
            run = _ActiveRun(run_id, record["mode"], record["engine"],
                             [p["key"] for p in record["phases"]])
            run.done_keys = [p["key"] for p in record["phases"]
                             if p["status"] == "done" and p["key"] not in reset]
            self.active = run

        runs_repo.set_status(run_id, "running", error="")
        self._emit(run, "log", "started",
                   f"rerunning '{phase_key}' — also redoing {', '.join(reset[1:]) or 'nothing downstream'}")
        run.task = asyncio.create_task(self._execute(run))
        return runs_repo.get(run_id)

    async def stop(self, run_id: str | None = None) -> dict | None:
        """Cancel the active run: graceful first, hard after a grace period."""
        from core.repo import runs as runs_repo

        run = self.active
        if run is None or (run_id and run.id != run_id):
            return None

        run.cancelled = True
        self._emit(run, "log", "progress", "stop requested — finishing the current step")

        if run.proc is not None and run.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                run.proc.terminate()
            try:
                await asyncio.wait_for(run.proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._emit(run, "log", "progress", "step didn't exit — forcing it")
                with contextlib.suppress(ProcessLookupError, OSError):
                    run.proc.kill()

        if run.engine is not None:
            with contextlib.suppress(Exception):
                await run.engine.stop()

        if run.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(run.task), timeout=20)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                run.task.cancel()
        return runs_repo.get(run.id)

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    async def _execute(self, run: _ActiveRun) -> None:
        from core.repo import runs as runs_repo

        runs_repo.set_status(run.id, "running")
        self._emit(run, "log", "started",
                   f"run {run.id} started ({run.engine_name}, mode={run.mode})")

        tail_stop = asyncio.Event()
        tail_task = asyncio.create_task(self._tail_layer_a(run, tail_stop))
        previous_env = self._apply_env(run)
        failed: list[str] = []

        try:
            statuses = {p["key"]: p["status"]
                        for p in (runs_repo.get(run.id) or {}).get("phases", [])}
            for key in run.keys:
                if statuses.get(key) in ("done", "skipped"):
                    run.done_keys.append(key)
                    continue

                phase = P.get(key)
                if run.cancelled:
                    runs_repo.phase_finish(run.id, key, "cancelled")
                    continue
                if failed and not phase.always_attempt:
                    runs_repo.phase_finish(run.id, key, "skipped",
                                           error=f"skipped after '{failed[-1]}' failed")
                    self._emit(run, key, "error", f"skipped — '{failed[-1]}' failed earlier")
                    continue

                ok = await self._run_phase(run, phase)
                if ok:
                    run.done_keys.append(key)
                elif not phase.optional:
                    failed.append(key)

            await asyncio.sleep(0.4)  # let the tail drain Layer A's last lines
            self._finalize(run, failed)
        except asyncio.CancelledError:
            runs_repo.set_status(run.id, "cancelled", ended=True)
            self._emit(run, "done", "error", "run cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            runs_repo.set_status(run.id, "error", error=str(exc), ended=True)
            self._emit(run, "done", "error", str(exc))
        finally:
            tail_stop.set()
            with contextlib.suppress(Exception):
                await tail_task
            self._restore_env(previous_env)
            self._close_subscribers(run)
            if self.active is run:
                self.active = None

    def _finalize(self, run: _ActiveRun, failed: list[str]) -> None:
        from core.repo import runs as runs_repo

        if run.cancelled:
            status, message = "cancelled", "run stopped"
        elif failed:
            status = "error"
            message = f"finished with problems in: {', '.join(failed)}"
        else:
            status, message = "done", "run complete"

        self._update_scan(run)
        summary = self._summary(run, failed)
        runs_repo.set_status(run.id, status, error="" if status != "error" else message,
                             summary=summary, ended=True)
        self._emit(run, "done", "done" if status == "done" else "error", message,
                   data={"summary": summary, "failed": failed})

    async def _run_phase(self, run: _ActiveRun, phase: P.Phase) -> bool:
        from core.repo import runs as runs_repo

        run.current_phase = phase.key
        runs_repo.phase_start(run.id, phase.key)
        self._emit(run, phase.key, "started", phase.label)
        started = time.monotonic()

        missing = [name for name in phase.inputs if not run.store.exists(name)]
        if missing and not phase.always_attempt:
            detail = f"missing input: {', '.join(missing)}"
            if phase.optional:
                runs_repo.phase_finish(run.id, phase.key, "skipped", error=detail)
                self._emit(run, phase.key, "error", f"skipped — {detail}")
                return True
            runs_repo.phase_finish(run.id, phase.key, "error", error=detail)
            self._emit(run, phase.key, "error", detail)
            return False

        last_error = ""
        for attempt in range(1, phase.max_attempts + 1):
            if run.cancelled:
                runs_repo.phase_finish(run.id, phase.key, "cancelled")
                self._emit(run, phase.key, "error", "cancelled")
                return False
            if attempt > 1:
                delay = min(30, 2 ** attempt)
                self._emit(run, phase.key, "progress",
                           f"retrying in {delay}s (attempt {attempt}/{phase.max_attempts})")
                await asyncio.sleep(delay)
                runs_repo.phase_start(run.id, phase.key)

            try:
                if phase.kind == "python":
                    ok, last_error, usage = await self._run_script(run, phase)
                else:
                    ok, last_error, usage = await self._run_llm(run, phase)
            except asyncio.CancelledError:
                runs_repo.phase_finish(run.id, phase.key, "cancelled")
                raise
            except Exception as exc:  # noqa: BLE001
                ok, last_error, usage = False, str(exc), None

            cost, tokens_in, tokens_out = self._record_cost(run, phase, usage)
            if ok:
                artifact = self._artifact_summary(run, phase, time.monotonic() - started)
                runs_repo.phase_finish(run.id, phase.key, "done", artifact=artifact,
                                       cost_usd=cost, tokens_in=tokens_in,
                                       tokens_out=tokens_out)
                self._emit(run, phase.key, "done", self._done_message(phase, artifact),
                           data=artifact)
                return True

            if run.cancelled or not _is_transient(last_error) or attempt == phase.max_attempts:
                break

        status = "skipped" if phase.optional else "error"
        runs_repo.phase_finish(run.id, phase.key, status, error=last_error)
        self._emit(run, phase.key, "error",
                   f"{'skipped' if phase.optional else 'failed'}: {last_error}"[:500])
        return phase.optional

    # ------------------------------------------------------------------ #
    # Phase kinds
    # ------------------------------------------------------------------ #
    async def _run_script(self, run: _ActiveRun, phase: P.Phase):
        """Run a Layer A script as a child process, streaming its output as events."""
        from engines.base import SUBPROCESS_STREAM_LIMIT

        argv = [sys.executable, *(str(REPO_DIR / part) if part.endswith(".py") else part
                                  for part in phase.script)]
        argv += self._script_args(run, phase)

        env = dict(os.environ)
        env.update(run.store.env())
        env.setdefault("PYTHONUNBUFFERED", "1")

        self._emit(run, phase.key, "progress", f"$ {Path(argv[1]).name} "
                   f"{' '.join(argv[2:])}".strip(), origin="tool")

        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(REPO_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=SUBPROCESS_STREAM_LIMIT,
            env=env,
            start_new_session=True,  # so terminate() reaches the whole process group
        )
        run.proc = proc
        tail: list[str] = []
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                tail.append(line)
                del tail[:-40]
                self._emit(run, phase.key, "progress", line[:400], origin="tool")
            rc = await proc.wait()
        finally:
            run.proc = None

        if rc == 0:
            return True, "", None
        if run.cancelled or rc in (-signal.SIGTERM, -signal.SIGKILL, 143, 137):
            return False, "cancelled", None
        return False, "\n".join(tail[-6:]) or f"exit code {rc}", None

    def _script_args(self, run: _ActiveRun, phase: P.Phase) -> list[str]:
        """Per-phase CLI arguments — everything else comes from the run environment."""
        if phase.key == "scrape":
            if run.mode == "native":
                return ["--native-only"]
            return []
        if phase.key == "persist":
            args = [run.store.path("scored").as_posix()]
            scan_id = self._scan_id(run)
            if scan_id:
                args += ["--scan-id", str(scan_id)]
            return args
        if phase.key == "report":
            return ["--input", run.store.path("scored").as_posix(),
                    "--output", str(self._report_path(run))]
        if phase.key == "notify":
            return ["--input", run.store.path("scored").as_posix(),
                    "--run-mode", run.mode,
                    "--report", str(self._report_path(run))]
        return []

    async def _run_llm(self, run: _ActiveRun, phase: P.Phase):
        """Hand one phase to the configured agent and normalize its events."""
        import engines
        from core import model_catalog
        from core.repo import settings as settings_repo

        cfg = settings_repo.engine_config()
        kwargs: dict = {}

        # Model choice is per-phase, not a single engine-wide setting: a phase tagged
        # "fast" (mostly WebSearch/WebFetch — discover, salary) runs on the cheap tier
        # by default, "reasoning" phases (relevance, score, intel) get the stronger one.
        # model_locked phases (salary) ignore whatever the user configured and always
        # get their tier's default — see orchestrator.phases and core.model_catalog.
        phase_cfg = settings_repo.pipeline_phase_config().get(phase.key, {})
        requested = None if phase.model_locked else phase_cfg.get("model")
        model = model_catalog.resolve(run.engine_name, phase.model_tier, requested)
        if model and run.engine_name in ("claude_code", "claude_api", "gemini"):
            kwargs["model"] = model

        if run.engine_name == "claude_code" and cfg.get("permission_mode"):
            kwargs["permission_mode"] = cfg["permission_mode"]
        if run.engine_name == "generic_cli" and cfg.get("command_template"):
            kwargs["command_template"] = cfg["command_template"]

        engine = engines.get_engine(run.engine_name, **kwargs)
        ok, reason = engine.available()
        if not ok:
            return False, f"engine '{run.engine_name}' unavailable: {reason}", None

        run.engine = engine
        loop_events: list = []

        def on_event(ev):
            payload = ev.to_dict()
            # Attribute the agent's narration to the phase that produced it, so the UI
            # can file each log line under the right card.
            self._emit(run, payload.get("stage") or "log", payload.get("status", "progress"),
                       payload.get("msg", ""), data=payload.get("data") or {},
                       origin=payload.get("origin", "engine"), phase_key=phase.key)
            loop_events.append(payload)

        try:
            result = await engine.run(self._program_for(run, phase), run.id, on_event)
        finally:
            run.engine = None

        if not result.ok:
            return False, result.error or "engine reported failure", result.usage
        if phase.output and not run.store.exists(phase.output):
            return False, (f"the agent finished without writing "
                           f"{phase.output}.json"), result.usage
        return True, "", result.usage

    def _skill_body(self, phase: P.Phase) -> str:
        """Read the phase's SKILL.md, minus its YAML frontmatter.

        Embedding the file content — rather than passing `phase.skill` (e.g.
        "/job-phase-discover") through as a literal slash command — means the agent
        gets the same instructions regardless of whether the invoking CLI has that
        command registered. `.claude/commands/*.md` is personal, gitignored config and
        never shipped in the wheel, so relying on slash-command resolution broke every
        LLM phase for anyone without a hand-maintained mirror of it (see git history).

        The frontmatter (`---\\nname: ...\\ndescription: ...\\n---`) is skill-discovery
        metadata, not instructions, and it makes the program text start with `---` —
        which Commander.js-based CLIs (including `claude`) reject as "unknown option"
        when it lands as the value of `-p`/`--print`. Stripping it fixes both.
        """
        name = phase.skill.lstrip("/")
        path = REPO_DIR / "skills" / name / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        if text.startswith("---\n"):
            end = text.find("\n---", 4)
            if end != -1:
                text = text[end + 4:]
        return text.lstrip("\n")

    def _program_for(self, run: _ActiveRun, phase: P.Phase) -> str:
        """The prompt handed to the agent: the phase skill plus its concrete paths."""
        lines = [
            self._skill_body(phase),
            "",
            "RUN CONTEXT (authoritative — use these exact paths):",
            f"  run_id:      {run.id}",
            f"  run_dir:     {run.store.dir}",
            f"  run_mode:    {run.mode}",
        ]
        for name in phase.inputs:
            lines.append(f"  input:       {run.store.path(name)}")
        if phase.output:
            lines.append(f"  output:      {run.store.path(phase.output)}")
        lines += [
            "",
            "Do only this phase. Write the output artifact, then stop — do not run any "
            "later phase of the pipeline, and do not ask questions.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Bookkeeping
    # ------------------------------------------------------------------ #
    def _record_cost(self, run: _ActiveRun, phase: P.Phase, usage) -> tuple[float, int, int]:
        if usage is None:
            return 0.0, 0, 0
        from core import pricing
        from core.repo import cost as cost_repo

        usd, source = pricing.price_usage(usage, engine=run.engine_name)
        tokens_in = getattr(usage, "tokens_in", 0) or 0
        tokens_out = getattr(usage, "tokens_out", 0) or 0
        if not (tokens_in or tokens_out or usd):
            return 0.0, 0, 0
        cost_repo.record(
            engine=run.engine_name, model=getattr(usage, "model", "") or "",
            tokens_in=tokens_in, tokens_out=tokens_out,
            cache_read=getattr(usage, "cache_read", 0) or 0,
            cache_write=getattr(usage, "cache_write", 0) or 0,
            usd=usd, source=source, run_id=run.id, phase_key=phase.key, kind="run",
        )
        return usd, tokens_in, tokens_out

    def _artifact_summary(self, run: _ActiveRun, phase: P.Phase, seconds: float) -> dict:
        summary: dict = {"duration_s": round(seconds, 1)}
        if phase.output:
            summary["artifact"] = phase.output
            summary["path"] = str(run.store.path(phase.output))
            summary["count"] = run.store.count(phase.output)
        if phase.key == "scrape":
            status = run.store.read("scrape_status", {}) or {}
            if isinstance(status, dict):
                summary["sources"] = status
        if phase.key == "report":
            report = self._report_path(run)
            summary["report"] = str(report) if report.exists() else ""
        if phase.key == "notify":
            summary["channels"] = (run.store.read("notify_receipt", {}) or {}).get("channels", {})
        return summary

    @staticmethod
    def _done_message(phase: P.Phase, artifact: dict) -> str:
        count = artifact.get("count")
        if count is not None:
            return f"{phase.label} — {count} jobs"
        return phase.label

    def _report_path(self, run: _ActiveRun) -> Path:
        from core.paths import reports_dir
        reports_dir().mkdir(parents=True, exist_ok=True)
        return reports_dir() / f"{run.id}-{run.mode}.xlsx"

    def _scan_id(self, run: _ActiveRun) -> int | None:
        from core.repo import runs as runs_repo
        return runs_repo.scan_id_for_run(run.id)

    def _update_scan(self, run: _ActiveRun) -> None:
        from core.models import utcnow
        from core.repo import runs as runs_repo

        from core.repo import jobs as jobs_repo

        report = self._report_path(run)
        status = run.store.read("scrape_status", {}) or {}
        source_counts = status if isinstance(status, dict) else {}

        scan_id = self._scan_id(run)
        jobs_new = jobs_repo.counts_for_scan(scan_id)["new"] if scan_id else 0

        runs_repo.update_scan(
            run.id,
            ended_at=utcnow(),
            jobs_raw=run.store.count("raw"),
            jobs_after_filter=run.store.count("filtered"),
            jobs_scored=run.store.count("scored"),
            jobs_new=jobs_new,
            report_path=str(report) if report.exists() else "",
            source_counts=source_counts,
        )
        # Jobs whose deadline passed while this run was going are stale from now on.
        with contextlib.suppress(Exception):
            jobs_repo.mark_stale()

    def _summary(self, run: _ActiveRun, failed: list[str]) -> str:
        parts = [
            f"{run.store.count('raw')} scraped",
            f"{run.store.count('filtered')} after filters",
            f"{run.store.count('scored')} scored",
        ]
        if failed:
            parts.append(f"problems in {', '.join(failed)}")
        return " · ".join(parts)

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    def _emit(self, run: _ActiveRun, stage: str, status: str, msg: str, *,
              data: dict | None = None, origin: str = "orchestrator",
              phase_key: str | None = None) -> None:
        from core.repo import runs as runs_repo

        event = {
            "stage": stage,
            "status": status,
            "msg": msg,
            "data": data or {},
            "origin": origin,
            "phase_key": phase_key if phase_key is not None else (
                run.current_phase if stage not in ("log", "done") else run.current_phase),
        }
        try:
            stored = runs_repo.add_event(run.id, event)
        except Exception:  # noqa: BLE001 — a logging failure must not kill a run
            stored = {**event, "run_id": run.id, "seq": -1}
        stored["progress"] = P.progress(run.done_keys)
        self._broadcast(run, stored)

    def _broadcast(self, run: _ActiveRun, event: dict) -> None:
        for q in list(run.subscribers):
            try:
                q.put_nowait(event)
            except Exception:  # noqa: BLE001 — a slow client must not block the run
                pass

    async def _tail_layer_a(self, run: _ActiveRun, stop: asyncio.Event) -> None:
        """Follow events.jsonl so Layer A's authoritative counts reach the UI live."""
        path = run.store.events_path()
        pos = 0
        while not stop.is_set():
            try:
                if path.exists():
                    with path.open("r", encoding="utf-8") as fh:
                        fh.seek(pos)
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            self._emit(run, record.get("stage", "log"),
                                       record.get("status", "progress"),
                                       record.get("msg", ""),
                                       data=record.get("data") or {},
                                       origin="layerA")
                        pos = fh.tell()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.3)

    # -- subscriptions --------------------------------------------------- #
    def subscribe(self, run_id: str, after_seq: int = 0) -> asyncio.Queue:
        """Queue of events for `run_id`, replaying history from `after_seq` first."""
        from core.repo import runs as runs_repo

        q: asyncio.Queue = asyncio.Queue()
        for event in runs_repo.events(run_id, after_seq=after_seq):
            q.put_nowait(event)

        run = self.active
        if run is not None and run.id == run_id:
            run.subscribers.add(q)
        else:
            q.put_nowait(None)  # finished run: history only, then end the stream
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        run = self.active
        if run is not None and run.id == run_id:
            run.subscribers.discard(q)

    def _close_subscribers(self, run: _ActiveRun) -> None:
        for q in list(run.subscribers):
            with contextlib.suppress(Exception):
                q.put_nowait(None)
        run.subscribers.clear()

    # -- environment ----------------------------------------------------- #
    def _apply_env(self, run: _ActiveRun) -> dict[str, str | None]:
        """Publish the run to in-process code (the LLM engines) as well as children."""
        previous: dict[str, str | None] = {}
        env = run.store.env()
        scan_id = self._scan_id(run)
        if scan_id:
            env["JOBPILOT_SCAN_ID"] = str(scan_id)
        for key, value in env.items():
            previous[key] = os.environ.get(key)
            os.environ[key] = value
        return previous

    @staticmethod
    def _restore_env(previous: dict[str, str | None]) -> None:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # -- status ---------------------------------------------------------- #
    def is_busy(self) -> bool:
        return self.active is not None

    def active_run_id(self) -> str | None:
        return self.active.id if self.active else None


# module-level singleton — one orchestrator per service process
orchestrator = Orchestrator()
