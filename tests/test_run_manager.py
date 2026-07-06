"""RunManager end-to-end with a fake engine — validates the SSE core without an LLM.

Exercises: events.jsonl tailing (Layer A path), engine on_event fan-out (Layer B path),
ordered broadcast, subscriber replay + sentinel, and run persistence.
"""
import asyncio
import json
from pathlib import Path

import engines
import run_manager
from engines.base import RunEvent, RunResult


class FakeEngine:
    """Emits both a Layer A events.jsonl line and engine-level RunEvents."""
    name = "fake"
    label = "Fake"
    metered = False

    def available(self):
        return True, ""

    async def run(self, program, run_id, on_event):
        run_dir = Path(f"/tmp/jobpilot_run_{run_id}")
        # simulate Layer A writing to events.jsonl (as run_events.emit would)
        with (run_dir / "events.jsonl").open("a") as fh:
            fh.write(json.dumps({"stage": "scrape", "status": "done",
                                 "msg": "42 raw", "data": {"total": 42}}) + "\n")
            fh.write(json.dumps({"stage": "filter", "status": "done",
                                 "msg": "10 kept", "data": {"kept": 10}}) + "\n")
        await asyncio.sleep(0.4)  # let the tailer pick up the lines
        # engine-level Layer B narration
        on_event(RunEvent("score", "done", "scored 10", data={"n": 10}))
        on_event(RunEvent("notify", "done", "digest sent"))
        return RunResult(ok=True, exit_code=0, artifacts={"final_text": "Top: Acme SDE (81)"})


def _install_fake(monkeypatch):
    monkeypatch.setattr(engines, "get_engine", lambda name=None, **k: FakeEngine())
    monkeypatch.setattr(run_manager.engines, "get_engine",
                        lambda name=None, **k: FakeEngine())


def test_run_streams_layerA_and_engine_events(monkeypatch):
    _install_fake(monkeypatch)
    mgr = run_manager.RunManager()

    async def scenario():
        run = await mgr.start_run(mode="native", engine_name="fake")
        q = mgr.subscribe(run)
        seen = []
        while True:
            ev = await asyncio.wait_for(q.get(), timeout=10)
            if ev is None:
                break
            seen.append(ev)
        return run, seen

    run, seen = asyncio.run(scenario())
    stages = {(e["stage"], e["status"]) for e in seen}
    # Layer A (via events.jsonl tail)
    assert ("scrape", "done") in stages
    assert ("filter", "done") in stages
    # Layer B (via engine on_event)
    assert ("score", "done") in stages
    assert ("notify", "done") in stages
    # terminal
    assert run.status == "done"
    # monotonic seq ordering
    seqs = [e["seq"] for e in seen]
    assert seqs == sorted(seqs)


def test_busy_rejects_second_run(monkeypatch):
    _install_fake(monkeypatch)
    mgr = run_manager.RunManager()

    async def scenario():
        await mgr.start_run(mode="native", engine_name="fake")
        try:
            await mgr.start_run(mode="native", engine_name="fake")
            return False
        except run_manager.RunBusyError:
            return True

    assert asyncio.run(scenario()) is True


def test_persists_history(monkeypatch, tmp_path):
    _install_fake(monkeypatch)
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    mgr = run_manager.RunManager()

    async def scenario():
        run = await mgr.start_run(mode="native", engine_name="fake")
        q = mgr.subscribe(run)
        while (await asyncio.wait_for(q.get(), timeout=10)) is not None:
            pass
        return run.id

    run_id = asyncio.run(scenario())
    hist = mgr.history()
    assert any(h["id"] == run_id for h in hist)
