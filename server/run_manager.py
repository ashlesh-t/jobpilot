"""Thin HTTP-facing adapter over the phase orchestrator.

All run logic — phase ordering, cancellation, retries, artifacts, cost — lives in
`orchestrator/runner.py`. This module exists so `server/app.py` has one small, stable
surface to call and so run records are shaped for JSON responses in one place.

v1's RunManager owned the execution loop itself and kept run state in memory. It is gone:
state now lives in the database, which is why a finished run's timeline survives a
service restart and why "resume" is possible at all.

Every method here takes `user_id` first and threads it straight into the orchestrator,
which keeps one active run per account rather than one globally.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from orchestrator import phases as phase_registry  # noqa: E402
from orchestrator.runner import (  # noqa: E402
    RunBusyError,
    UnknownRunError,
    orchestrator,
)

__all__ = ["manager", "RunBusyError", "UnknownRunError"]


class RunManager:
    """Run control for the API layer."""

    # -- lifecycle ------------------------------------------------------- #
    async def start_run(self, user_id: int, *, mode: str = "auto", engine_name: str | None = None,
                        only: list[str] | None = None, skip: list[str] | None = None,
                        trigger: str = "manual", slot_name: str = "") -> dict:
        # No explicit selection from this caller — fall back to whatever was saved in
        # the pipeline editor, so a scheduled run respects it exactly like a manual one.
        if only is None and skip is None:
            from core.repo import settings as settings_repo
            only = settings_repo.enabled_phase_keys(user_id)
        return await orchestrator.start(user_id, mode=mode, engine=engine_name, only=only,
                                        skip=skip, trigger=trigger, slot_name=slot_name)

    async def resume(self, user_id: int, run_id: str) -> dict:
        return await orchestrator.resume(user_id, run_id)

    async def rerun_phase(self, user_id: int, run_id: str, phase_key: str) -> dict:
        return await orchestrator.rerun(user_id, run_id, phase_key)

    async def stop(self, user_id: int, run_id: str | None = None) -> dict | None:
        return await orchestrator.stop(user_id, run_id)

    # -- reads ----------------------------------------------------------- #
    def active(self, user_id: int) -> dict | None:
        from core.repo import runs as runs_repo
        run_id = orchestrator.active_run_id(user_id)
        return runs_repo.get(user_id, run_id) if run_id else None

    def get(self, user_id: int, run_id: str) -> dict | None:
        from core.repo import runs as runs_repo
        run = runs_repo.get(user_id, run_id)
        if run is None:
            return None
        run["artifacts"] = self.artifacts(user_id, run_id)
        run["progress"] = phase_registry.progress(
            [p["key"] for p in run["phases"] if p["status"] == "done"])
        return run

    def history(self, user_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
        from core.repo import runs as runs_repo
        return runs_repo.history(user_id, limit=limit, offset=offset)

    def events(self, run_id: str, after_seq: int = 0) -> list[dict]:
        from core.repo import runs as runs_repo
        return runs_repo.events(run_id, after_seq=after_seq)

    def artifacts(self, user_id: int, run_id: str) -> list[dict]:
        from orchestrator.artifacts import ArtifactStore
        try:
            return ArtifactStore(user_id, run_id).inventory()
        except Exception:  # noqa: BLE001
            return []

    def top_jobs(self, user_id: int, run_id: str, limit: int = 10) -> list[dict]:
        """Best matches from this run's own artifacts.

        Run-scoped by construction — v1 read the newest file on disk regardless of which
        run asked, so historical runs showed someone else's results.
        """
        from orchestrator.artifacts import ArtifactStore

        store = ArtifactStore(user_id, run_id)
        for name in ("scored", "relevant", "filtered"):
            jobs = store.read(name, None)
            if not isinstance(jobs, list) or not jobs:
                continue
            jobs = sorted(
                jobs,
                key=lambda j: float(j.get("effective_score") or j.get("score") or 0),
                reverse=True)
            return [
                {
                    "job_id": j.get("job_id", ""),
                    "company": j.get("company", ""),
                    "role": j.get("role", ""),
                    "location": j.get("location", ""),
                    "score": j.get("score", 0),
                    "salary": j.get("market_salary") or j.get("salary_range") or "",
                    "url": j.get("application_url", ""),
                }
                for j in jobs[:limit]
            ]
        return []

    # -- streaming ------------------------------------------------------- #
    def subscribe(self, user_id: int, run_id: str, after_seq: int = 0):
        return orchestrator.subscribe(user_id, run_id, after_seq=after_seq)

    def unsubscribe(self, user_id: int, run_id: str, q) -> None:
        orchestrator.unsubscribe(user_id, run_id, q)

    # -- misc ------------------------------------------------------------ #
    def is_busy(self, user_id: int) -> bool:
        return orchestrator.is_busy(user_id)

    @staticmethod
    def catalog() -> list[dict]:
        return phase_registry.catalog()

    @staticmethod
    def reset_orphans() -> int:
        """Mark runs interrupted by a crash or restart. Called once at startup."""
        from core.repo import runs as runs_repo
        return runs_repo.reset_orphans()


manager = RunManager()
