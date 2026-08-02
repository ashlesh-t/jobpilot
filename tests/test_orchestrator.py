"""Orchestrator tests — ordering, artifacts, stop, resume, rerun, retries, cost.

The pipeline's real phases are replaced with tiny stand-ins so the suite is fast and
offline, but the code under test is the actual runner: the same scheduling, the same
subprocess handling, the same invalidation rules.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from orchestrator import phases as P
from orchestrator.artifacts import ArtifactStore
from orchestrator.runner import Orchestrator, RunBusyError


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _writer(name: str, count: int = 3) -> str:
    """Inline python that writes `count` fake jobs into artifact `name`."""
    return (
        "import json, os, pathlib;"
        f"p = pathlib.Path(os.environ['JOBPILOT_RUN_DIR']) / '{name}.json';"
        f"p.write_text(json.dumps([{{'job_id': f'j{{i}}', 'company': 'Acme',"
        f" 'role': 'Backend', 'score': 70 + i}} for i in range({count})]));"
        f"print('[test] wrote {name}')"
    )


TEST_PHASES = (
    P.Phase(key="scrape", label="Scrape", help="", kind="python",
            output="raw", script=("-c", _writer("raw")), weight=1.0),
    P.Phase(key="filter", label="Filter", help="", kind="python",
            depends_on=("scrape",), inputs=("raw",), output="filtered",
            script=("-c", _writer("filtered", 2)), weight=1.0),
    P.Phase(key="score", label="Score", help="", kind="llm",
            depends_on=("filter",), inputs=("filtered",), output="scored",
            skill="/job-phase-score", weight=1.0),
    P.Phase(key="report", label="Report", help="", kind="python",
            depends_on=("score",), inputs=("scored",),
            script=("-c", "print('[test] report built')"),
            always_attempt=True, weight=1.0),
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("JOBPILOT_RUN_DIR", raising=False)
    from core import db

    db.dispose()
    db.init_db()
    yield tmp_path
    db.dispose()


@pytest.fixture()
def pipeline(store, monkeypatch):
    """Swap the real phase registry for the tiny test pipeline."""
    monkeypatch.setattr(P, "PHASES", TEST_PHASES)
    monkeypatch.setattr(P, "PHASE_KEYS", tuple(p.key for p in TEST_PHASES))
    monkeypatch.setattr(P, "BY_KEY", {p.key: p for p in TEST_PHASES})
    monkeypatch.setattr(P, "TOTAL_WEIGHT", sum(p.weight for p in TEST_PHASES))
    return TEST_PHASES


class FakeEngine:
    """Stands in for a provider adapter. Writes the phase's output artifact."""
    label = "fake"
    metered = False

    def __init__(self, *, fail: str = "", hang: bool = False, usage=None):
        self.fail = fail
        self.hang = hang
        self.usage = usage
        self.stopped = False
        self.calls: list[str] = []

    def available(self):
        return True, ""

    async def run(self, program, run_id, on_event):
        from engines.base import RunEvent, RunResult, Usage
        from orchestrator.artifacts import ArtifactStore as _Store

        self.calls.append(program)
        on_event(RunEvent("score", "progress", "thinking", origin="engine"))

        if self.hang:
            # Mirror a real adapter: keep working until stop() is called, then bail out.
            for _ in range(600):
                if self.stopped:
                    return RunResult(ok=False, error="cancelled")
                await asyncio.sleep(0.05)
            return RunResult(ok=False, error="hung")

        if self.fail:
            return RunResult(ok=False, error=self.fail, usage=self.usage or Usage())

        store = _Store(run_id)
        store.write("scored", [{"job_id": "j0", "company": "Acme", "score": 88}])
        return RunResult(ok=True, exit_code=0, usage=self.usage or Usage())

    async def stop(self):
        self.stopped = True


@pytest.fixture()
def fake_engine(monkeypatch):
    holder = {"engine": FakeEngine()}

    def _get_engine(name=None, **kwargs):
        return holder["engine"]

    import engines
    monkeypatch.setattr(engines, "get_engine", _get_engine)
    return holder


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_real_registry_is_ordered_and_consistent():
    from orchestrator import phases as real

    assert real.PHASE_KEYS[0] == "scrape"
    assert real.PHASE_KEYS[-1] == "notify"
    for phase in real.PHASES:
        for dep in phase.depends_on:
            assert real.position(dep) < real.position(phase.key), \
                f"{phase.key} depends on a later phase {dep}"
        assert phase.kind in ("python", "llm")
        if phase.kind == "llm":
            assert phase.skill, f"{phase.key} is an llm phase with no skill"
        else:
            assert phase.script, f"{phase.key} is a python phase with no script"


def test_every_llm_phase_has_a_skill_file():
    from pathlib import Path

    from orchestrator import phases as real

    repo = Path(__file__).resolve().parent.parent
    for phase in real.PHASES:
        if phase.kind != "llm":
            continue
        name = phase.skill.lstrip("/")
        assert (repo / "skills" / name / "SKILL.md").exists(), \
            f"missing skills/{name}/SKILL.md for phase {phase.key}"


def test_downstream_invalidation_set():
    from orchestrator import phases as real

    assert real.downstream_of("report") == ["report", "notify"]
    assert real.downstream_of("report", inclusive=False) == ["notify"]
    assert real.downstream_of("scrape")[0] == "scrape"


def test_selection_filters_and_validates():
    from orchestrator import phases as real

    assert real.selection(only=["filter", "scrape"]) == ["scrape", "filter"]
    assert "notify" not in real.selection(skip=["notify"])
    with pytest.raises(ValueError):
        real.selection(only=["nope"])
    with pytest.raises(ValueError):
        real.selection(skip=list(real.PHASE_KEYS))


# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #
def test_artifacts_are_run_scoped(store):
    a, b = ArtifactStore("run-a"), ArtifactStore("run-b")
    a.write("raw", [1, 2, 3])
    b.write("raw", [9])
    # The v1 bug this prevents: both runs writing /tmp/jobpilot_raw.json.
    assert a.read("raw") == [1, 2, 3]
    assert b.read("raw") == [9]
    assert a.count("raw") == 3


def test_artifact_write_is_atomic(store):
    s = ArtifactStore("run-c")
    s.write("raw", [{"a": 1}])
    assert not list(s.dir.glob("*.tmp"))
    assert s.read("raw") == [{"a": 1}]


def test_artifact_inventory_lists_only_what_exists(store):
    s = ArtifactStore("run-d")
    s.write("raw", [1])
    s.write("scored", [1, 2])
    names = {i["name"] for i in s.inventory()}
    assert names == {"raw", "scored"}


def test_layer_a_scripts_honour_the_run_dir(store, monkeypatch):
    """jp_paths is the contract that keeps Layer A writing into the run directory."""
    import importlib

    monkeypatch.setenv("JOBPILOT_RUN_DIR", str(store / "runs" / "r1"))
    sys.path.insert(0, str(store))
    import jp_paths
    importlib.reload(jp_paths)
    assert jp_paths.artifact("raw").endswith("runs/r1/raw.json")

    monkeypatch.delenv("JOBPILOT_RUN_DIR")
    monkeypatch.delenv("JOBPILOT_RUN_ID", raising=False)
    importlib.reload(jp_paths)
    assert jp_paths.artifact("raw") == "/tmp/jobpilot_raw.json"


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
async def _drain(orch, run_id, timeout=30):
    for _ in range(int(timeout / 0.05)):
        if orch.active is None:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("run did not finish in time")


async def test_full_run_executes_every_phase(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    orch = Orchestrator()
    started = await orch.start(mode="native", engine="claude_code")
    await _drain(orch, started["id"])

    run = runs_repo.get(started["id"])
    assert run["status"] == "done"
    assert [p["status"] for p in run["phases"]] == ["done"] * 4

    store = ArtifactStore(run["id"])
    assert store.count("raw") == 3
    assert store.count("filtered") == 2
    assert store.count("scored") == 1

    scan = runs_repo.scan_for_run(run["id"])
    assert scan["jobs_raw"] == 3
    assert scan["jobs_after_filter"] == 2
    assert scan["jobs_scored"] == 1


async def test_events_are_persisted_and_replayable(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])

    events = runs_repo.events(started["id"])
    assert len(events) > 4
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    stages = {e["stage"] for e in events}
    assert {"scrape", "filter", "score", "done"} <= stages

    # A finished run replays from the database, so restarting the service doesn't
    # lose the timeline the way v1's in-memory history did.
    q = orch.subscribe(started["id"])
    first = q.get_nowait()
    assert first["run_id"] == started["id"]


async def test_second_run_is_rejected_while_one_is_active(pipeline, fake_engine):
    fake_engine["engine"] = FakeEngine(hang=True)
    orch = Orchestrator()
    started = await orch.start()
    await asyncio.sleep(0.6)
    with pytest.raises(RunBusyError):
        await orch.start()
    await orch.stop(started["id"])


# --------------------------------------------------------------------------- #
# Stop / resume / rerun
# --------------------------------------------------------------------------- #
async def test_stop_cancels_the_running_phase(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    engine = FakeEngine(hang=True)
    fake_engine["engine"] = engine

    orch = Orchestrator()
    started = await orch.start()
    for _ in range(100):                      # wait until scoring is actually in flight
        run = runs_repo.get(started["id"])
        if any(p["key"] == "score" and p["status"] == "running" for p in run["phases"]):
            break
        await asyncio.sleep(0.05)

    await orch.stop(started["id"])
    await _drain(orch, started["id"])

    run = runs_repo.get(started["id"])
    assert run["status"] == "cancelled"
    assert engine.stopped is True
    by_key = {p["key"]: p for p in run["phases"]}
    assert by_key["scrape"]["status"] == "done"
    assert by_key["score"]["status"] in ("cancelled", "error")


async def test_resume_skips_completed_phases(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    engine = FakeEngine(hang=True)
    fake_engine["engine"] = engine
    orch = Orchestrator()
    started = await orch.start()
    for _ in range(100):
        run = runs_repo.get(started["id"])
        if any(p["key"] == "score" and p["status"] == "running" for p in run["phases"]):
            break
        await asyncio.sleep(0.05)
    await orch.stop(started["id"])
    await _drain(orch, started["id"])

    scrape_started = runs_repo.get_phase(started["id"], "scrape")["started_at"]

    fake_engine["engine"] = FakeEngine()       # this time scoring succeeds
    await orch.resume(started["id"])
    await _drain(orch, started["id"])

    run = runs_repo.get(started["id"])
    assert run["status"] == "done"
    # Untouched: resume must not re-scrape, or "resume" would just mean "start over".
    assert runs_repo.get_phase(started["id"], "scrape")["started_at"] == scrape_started
    assert runs_repo.get_phase(started["id"], "score")["status"] == "done"


async def test_rerun_invalidates_downstream_phases(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])
    first_attempts = {p["key"]: p["attempt"] for p in runs_repo.get(started["id"])["phases"]}

    await orch.rerun(started["id"], "score")
    await _drain(orch, started["id"])

    run = runs_repo.get(started["id"])
    after = {p["key"]: p["attempt"] for p in run["phases"]}
    assert run["status"] == "done"
    # score and report re-ran; scrape and filter did not.
    assert after["score"] == first_attempts["score"] + 1
    assert after["report"] == first_attempts["report"] + 1
    assert after["scrape"] == first_attempts["scrape"]
    assert after["filter"] == first_attempts["filter"]


async def test_rerun_rejects_an_unknown_phase(pipeline, fake_engine):
    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])
    with pytest.raises(ValueError):
        await orch.rerun(started["id"], "not-a-phase")


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #
async def test_failed_phase_skips_dependents_but_still_reports(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    fake_engine["engine"] = FakeEngine(fail="model said no")
    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])

    run = runs_repo.get(started["id"])
    by_key = {p["key"]: p for p in run["phases"]}
    assert run["status"] == "error"
    assert by_key["score"]["status"] == "error"
    # report is always_attempt: the user still gets whatever was gathered.
    assert by_key["report"]["status"] == "done"


async def test_transient_failure_is_retried(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    attempts = {"n": 0}

    class Flaky(FakeEngine):
        async def run(self, program, run_id, on_event):
            attempts["n"] += 1
            if attempts["n"] == 1:
                from engines.base import RunResult
                return RunResult(ok=False, error="connection reset by peer")
            return await FakeEngine.run(self, program, run_id, on_event)

    fake_engine["engine"] = Flaky()
    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])

    assert attempts["n"] == 2
    assert runs_repo.get_phase(started["id"], "score")["status"] == "done"


async def test_permanent_failure_is_not_retried(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    engine = FakeEngine(fail="the profile is missing required fields")
    fake_engine["engine"] = engine
    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])

    assert len(engine.calls) == 1          # no pointless retry of a real fault
    assert runs_repo.get_phase(started["id"], "score")["status"] == "error"


async def test_missing_output_artifact_is_a_failure(pipeline, fake_engine):
    """An agent that says "done" without writing its artifact has not done the phase."""
    from core.repo import runs as runs_repo

    class Liar(FakeEngine):
        async def run(self, program, run_id, on_event):
            from engines.base import RunResult
            return RunResult(ok=True, exit_code=0)

    fake_engine["engine"] = Liar()
    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])

    phase = runs_repo.get_phase(started["id"], "score")
    assert phase["status"] == "error"
    assert "scored.json" in phase["error"]


async def test_phase_selection_runs_only_what_was_asked(pipeline, fake_engine):
    from core.repo import runs as runs_repo

    orch = Orchestrator()
    started = await orch.start(only=["scrape", "filter"])
    await _drain(orch, started["id"])

    run = runs_repo.get(started["id"])
    assert [p["key"] for p in run["phases"]] == ["scrape", "filter"]
    assert run["status"] == "done"


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #
async def test_metered_usage_is_recorded_against_the_phase(pipeline, fake_engine):
    from engines.base import Usage
    from core.repo import cost as cost_repo
    from core.repo import runs as runs_repo

    fake_engine["engine"] = FakeEngine(
        usage=Usage(tokens_in=10_000, tokens_out=2_000,
                    model="claude-opus-5", source="metered"))
    orch = Orchestrator()
    started = await orch.start(engine="claude_api")
    await _drain(orch, started["id"])

    entries = cost_repo.for_run(started["id"])
    assert len(entries) == 1
    assert entries[0]["phase_key"] == "score"
    assert entries[0]["usd"] > 0

    run = runs_repo.get(started["id"])
    assert run["tokens_in"] == 10_000
    assert run["cost_usd"] > 0


async def test_subscription_usage_is_free_but_counted(pipeline, fake_engine):
    from engines.base import Usage
    from core.repo import cost as cost_repo

    fake_engine["engine"] = FakeEngine(
        usage=Usage(tokens_in=50_000, tokens_out=8_000,
                    model="claude-opus-5", source="subscription"))
    orch = Orchestrator()
    started = await orch.start(engine="claude_code")
    await _drain(orch, started["id"])

    summary = cost_repo.summary(run_id=started["id"])
    assert summary["usd"] == 0.0
    assert summary["subscription_tokens"] == 58_000


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
async def test_llm_program_pins_the_run_paths(pipeline, fake_engine):
    engine = FakeEngine()
    fake_engine["engine"] = engine
    orch = Orchestrator()
    started = await orch.start()
    await _drain(orch, started["id"])

    program = engine.calls[0]
    assert program.startswith("/job-phase-score")
    assert started["id"] in program
    assert "filtered.json" in program        # its input
    assert "scored.json" in program          # its output
    assert "do not run any later phase" in program.lower()


async def test_orphaned_runs_are_marked_after_a_restart(store):
    from core.repo import runs as runs_repo

    rid = runs_repo.new_run_id()
    runs_repo.create(rid, mode="auto", engine="claude_code", phase_keys=["scrape"])
    runs_repo.set_status(rid, "running")
    runs_repo.phase_start(rid, "scrape")

    assert runs_repo.reset_orphans() == 1
    run = runs_repo.get(rid)
    assert run["status"] == "error"
    assert "interrupted" in run["error"]
