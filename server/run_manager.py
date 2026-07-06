"""RunManager — orchestrates one pipeline run and streams its events.

Responsibilities:
  * Create the run scratch dir and set JOBPILOT_RUN_ID so Layer A emits to events.jsonl.
  * Tail events.jsonl (authoritative Layer A stage counts) and merge those with the
    engine's own tool/Layer-B narration into one ordered event stream.
  * Fan events out to any number of SSE subscribers.
  * Persist a run record (status + artifacts) under cache/runs/ for history.

Single active run at a time (a second concurrent start is rejected with RunBusyError);
for a single-user local tool that's the correct, predictable behaviour.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from common import REPO_DIR, jobpilot_dir, runs_dir, engine_config  # noqa: E402

import engines  # noqa: E402


class RunBusyError(Exception):
    """Raised when a run is requested while another is active."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Run:
    def __init__(self, run_id: str, mode: str, engine_name: str):
        self.id = run_id
        self.mode = mode                    # "full" | "native" | "auto"
        self.engine_name = engine_name
        self.status = "starting"            # starting|running|done|error
        self.started_at = _now_iso()
        self.ended_at: str | None = None
        self.error = ""
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.result_summary = ""
        self._seq = 0
        self.dir = Path(f"/tmp/jobpilot_run_{run_id}")

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "mode": self.mode,
            "engine": self.engine_name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "event_count": len(self.events),
            "summary": self.result_summary,
            "artifacts": self.artifacts(),
        }

    def artifacts(self) -> dict:
        report = _latest_report()
        top = _top_jobs()
        return {
            "report": str(report) if report else "",
            "top_jobs": top,
        }


class RunManager:
    def __init__(self):
        self.active: Run | None = None
        self.recent: dict[str, Run] = {}

    # -- lifecycle ------------------------------------------------------ #
    async def start_run(self, mode: str = "auto", engine_name: str | None = None) -> Run:
        if self.active and self.active.status in ("starting", "running"):
            raise RunBusyError(f"run {self.active.id} is already in progress")

        engine_name = engine_name or engine_config()["provider"]
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        run = Run(run_id, mode, engine_name)
        run.dir.mkdir(parents=True, exist_ok=True)
        (run.dir / "events.jsonl").write_text("")  # start clean
        self.active = run
        self.recent[run_id] = run
        asyncio.create_task(self._execute(run))
        return run

    async def _execute(self, run: Run) -> None:
        run.status = "running"
        self._broadcast(run, {"stage": "log", "status": "started",
                              "msg": f"run {run.id} started ({run.engine_name}, mode={run.mode})",
                              "origin": "manager", "data": {}})

        tail_stop = asyncio.Event()
        tail_task = asyncio.create_task(self._tail_events(run, tail_stop))

        try:
            engine = self._build_engine(run.engine_name)
            ok, reason = engine.available()
            if not ok:
                raise RuntimeError(f"engine '{run.engine_name}' unavailable: {reason}")

            program = self._program_for(run.mode)
            loop = asyncio.get_running_loop()

            def on_event(ev):
                # engine calls this synchronously on the loop thread
                d = ev.to_dict()
                self._broadcast(run, d)

            result = await engine.run(program, run.id, on_event)
            run.result_summary = (result.artifacts or {}).get("final_text", "")[:2000]
            if not result.ok:
                run.status = "error"
                run.error = result.error
            else:
                run.status = "done"
        except Exception as exc:  # noqa: BLE001
            run.status = "error"
            run.error = str(exc)
            self._broadcast(run, {"stage": "done", "status": "error",
                                  "msg": str(exc), "origin": "manager", "data": {}})
        finally:
            # let the tail drain the last Layer A lines, then stop it
            await asyncio.sleep(0.5)
            tail_stop.set()
            try:
                await tail_task
            except Exception:
                pass
            run.ended_at = _now_iso()
            self._broadcast(run, {"stage": "done", "status": run.status,
                                  "msg": f"run {run.status}", "origin": "manager", "data": {}})
            self._close_subscribers(run)
            self._persist(run)
            if self.active is run:
                self.active = None

    # -- event fan-out -------------------------------------------------- #
    def _broadcast(self, run: Run, event: dict) -> None:
        event.setdefault("origin", "engine")
        event.setdefault("data", {})
        event["seq"] = run.next_seq()
        event.setdefault("ts", _now_iso())
        event["run_id"] = run.id
        run.events.append(event)
        for q in list(run.subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def _close_subscribers(self, run: Run) -> None:
        for q in list(run.subscribers):
            try:
                q.put_nowait(None)  # sentinel: stream end
            except Exception:
                pass

    async def _tail_events(self, run: Run, stop: asyncio.Event) -> None:
        """Follow events.jsonl and broadcast Layer A lines as they appear."""
        path = run.dir / "events.jsonl"
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
                                rec = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            rec["origin"] = "layerA"
                            rec.pop("seq", None)  # re-sequenced by _broadcast
                            self._broadcast(run, rec)
                        pos = fh.tell()
            except Exception:
                pass
            await asyncio.sleep(0.3)

    # -- subscriptions -------------------------------------------------- #
    def subscribe(self, run: Run) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        # replay history so a late subscriber still sees the whole timeline
        for ev in run.events:
            q.put_nowait(ev)
        if run.status in ("done", "error"):
            q.put_nowait(None)
        else:
            run.subscribers.add(q)
        return q

    def unsubscribe(self, run: Run, q: asyncio.Queue) -> None:
        run.subscribers.discard(q)

    # -- helpers -------------------------------------------------------- #
    def _build_engine(self, name: str):
        cfg = engine_config()
        kwargs = {}
        if name == "claude_api" and cfg.get("model"):
            kwargs["model"] = cfg["model"]
        if name == "claude_code" and cfg.get("permission_mode"):
            kwargs["permission_mode"] = cfg["permission_mode"]
        return engines.get_engine(name, **kwargs)

    @staticmethod
    def _program_for(mode: str) -> str:
        base = "/job-search"
        if mode == "native":
            return base + "\n\nOVERRIDE: force RUN_MODE=native (native-only, skip Apify) this run."
        if mode == "full":
            return base + "\n\nOVERRIDE: force RUN_MODE=full (native + Apify) this run."
        return base  # auto — the skill decides via run_state.json

    def _persist(self, run: Run) -> None:
        try:
            (runs_dir() / f"{run.id}.json").write_text(
                json.dumps(run.to_public(), indent=2, ensure_ascii=False))
        except Exception:
            pass

    def history(self, limit: int = 50) -> list[dict]:
        out = []
        for p in sorted(runs_dir().glob("*.json"), reverse=True)[:limit]:
            try:
                out.append(json.loads(p.read_text()))
            except Exception:
                continue
        return out

    def get(self, run_id: str) -> Run | None:
        return self.recent.get(run_id)


# --------------------------------------------------------------------------- #
def _latest_report() -> Path | None:
    reports = jobpilot_dir() / "reports"
    if not reports.exists():
        return None
    files = sorted([*reports.glob("*.xlsx"), *reports.glob("*.csv")],
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _top_jobs(limit: int = 10) -> list[dict]:
    for path in ("/tmp/jobpilot_scored.json", "/tmp/jobpilot_filtered.json"):
        try:
            jobs = json.loads(Path(path).read_text())
        except Exception:
            continue
        jobs.sort(key=lambda j: float(j.get("score", j.get("match_score", 0)) or 0) *
                  float(j.get("location_weight") or 1.0), reverse=True)
        return [
            {
                "company": j.get("company", ""),
                "role": j.get("role", ""),
                "location": j.get("location", ""),
                "score": j.get("score", j.get("match_score", 0)),
                "salary": j.get("market_salary") or j.get("salary_range") or "",
                "url": j.get("application_url", ""),
            }
            for j in jobs[:limit]
        ]
    return []


# module-level singleton
manager = RunManager()
