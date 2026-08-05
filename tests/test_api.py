"""HTTP + SSE integration test — drives the real FastAPI app with a fake engine.

Covers the whole request path (POST /runs → SSE stream → artifacts → stop/resume/rerun)
without touching a real LLM, plus the read endpoints.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

from conftest import signup
from orchestrator import phases as P

# The service's own phase list, shrunk to something fast: two Layer A stand-ins around
# one LLM phase, so both execution paths and the artifact chain are exercised.
def _writer(name: str, count: int = 2) -> str:
    return (
        "import json, os, pathlib;"
        f"p = pathlib.Path(os.environ['JOBPILOT_RUN_DIR']) / '{name}.json';"
        f"p.write_text(json.dumps([{{'job_id': f'j{{i}}', 'company': 'Acme',"
        f" 'role': 'SDE', 'score': 80 + i, 'application_url': 'https://x.test'}}"
        f" for i in range({count})]));"
        f"print('[test] {name}')"
    )


TEST_PHASES = (
    P.Phase(key="scrape", label="Scrape", help="", kind="python",
            output="raw", script=("-c", _writer("raw"))),
    P.Phase(key="score", label="Score", help="", kind="llm",
            depends_on=("scrape",), inputs=("raw",), output="scored",
            skill="/job-phase-score"),
    P.Phase(key="report", label="Report", help="", kind="python",
            depends_on=("score",), inputs=("scored",),
            script=("-c", "print('[test] report')"), always_attempt=True),
)


class FakeEngine:
    name = "fake"
    label = "Fake"
    metered = False

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.stopped = False

    def available(self):
        return True, ""

    async def run(self, program, run_id, on_event):
        from engines.base import RunEvent, RunResult
        from orchestrator.artifacts import ArtifactStore

        on_event(RunEvent("score", "progress", "reading descriptions", origin="engine"))
        waited = 0.0
        while self.delay and waited < self.delay and not self.stopped:
            await asyncio.sleep(0.05)
            waited += 0.05
        if self.stopped:
            return RunResult(ok=False, error="cancelled")
        ArtifactStore(int(os.environ.get("JOBPILOT_USER_ID", "0")), run_id).write("scored", [
            {"job_id": "j0", "company": "Acme", "role": "SDE", "score": 88,
             "application_url": "https://x.test"}])
        on_event(RunEvent("score", "done", "scored 1", origin="engine"))
        return RunResult(ok=True, exit_code=0)

    async def stop(self):
        self.stopped = True


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("JOBPILOT_RUN_DIR", raising=False)

    from core import db
    db.dispose()
    db.init_db()

    monkeypatch.setattr(P, "PHASES", TEST_PHASES)
    monkeypatch.setattr(P, "PHASE_KEYS", tuple(p.key for p in TEST_PHASES))
    monkeypatch.setattr(P, "BY_KEY", {p.key: p for p in TEST_PHASES})
    monkeypatch.setattr(P, "TOTAL_WEIGHT", float(len(TEST_PHASES)))

    holder = {"engine": FakeEngine()}
    import engines
    monkeypatch.setattr(engines, "get_engine", lambda name=None, **k: holder["engine"])

    # Keep APScheduler out of the TestClient lifespan.
    import scheduler
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler.scheduler, "shutdown", lambda: None)

    import app as app_module
    with TestClient(app_module.app) as c:
        c.engine_holder = holder
        signup(c)
        yield c
    db.dispose()


def _consume_stream(client, run_id, stop_after=400):
    """Read the SSE stream until it ends, returning (stage, status) pairs."""
    stages = set()
    with client.stream("GET", f"/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        for i, line in enumerate(resp.iter_lines()):
            if i > stop_after:
                break
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload in ("", "{}"):
                continue
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if ev.get("stage"):
                stages.add((ev["stage"], ev.get("status")))
            if ev.get("stage") == "done" and ev.get("status") in ("done", "error"):
                break
    return stages


# --------------------------------------------------------------------------- #
def test_read_endpoints(client):
    assert client.get("/health").json()["ok"] is True
    assert "engines" in client.get("/engines").json()
    assert "rows" in client.get("/doctor").json()
    assert "slots" in client.get("/api/schedule").json()
    assert "engine" in client.get("/config").json()


def test_phase_catalog_is_exposed(client):
    phases = client.get("/phases").json()["phases"]
    assert [p["key"] for p in phases] == ["scrape", "score", "report"]
    assert all(p["label"] for p in phases)


def test_run_streams_events_and_produces_artifacts(client):
    r = client.post("/runs", json={"mode": "native", "engine": "fake"})
    assert r.status_code == 200
    body = r.json()
    run_id = body["run_id"]
    assert [p["key"] for p in body["phases"]] == ["scrape", "score", "report"]

    stages = _consume_stream(client, run_id)
    assert ("scrape", "done") in stages       # Layer A subprocess
    assert ("score", "done") in stages        # the agent phase
    assert ("done", "done") in stages

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] == "done"
    assert [p["status"] for p in detail["phases"]] == ["done"] * 3
    assert detail["top_jobs"][0]["company"] == "Acme"
    assert detail["progress"] == 1.0

    names = {a["name"] for a in client.get(f"/runs/{run_id}/artifacts").json()["artifacts"]}
    assert {"raw", "scored"} <= names

    artifact = client.get(f"/runs/{run_id}/artifacts/scored")
    assert artifact.status_code == 200
    assert json.loads(artifact.content)[0]["job_id"] == "j0"


def test_unknown_artifact_is_404(client):
    run_id = client.post("/runs", json={}).json()["run_id"]
    _consume_stream(client, run_id)
    assert client.get(f"/runs/{run_id}/artifacts/nonsense").status_code == 404


def test_finished_run_still_replays_its_timeline(client):
    """v1 lost the timeline once the run left memory; it is persisted now."""
    run_id = client.post("/runs", json={}).json()["run_id"]
    _consume_stream(client, run_id)

    replayed = _consume_stream(client, run_id)
    assert ("scrape", "done") in replayed
    assert ("done", "done") in replayed


def test_stop_then_resume(client):
    client.engine_holder["engine"] = FakeEngine(delay=30)
    run_id = client.post("/runs", json={}).json()["run_id"]

    for _ in range(100):
        detail = client.get(f"/runs/{run_id}").json()
        if any(p["key"] == "score" and p["status"] == "running" for p in detail["phases"]):
            break
    stopped = client.post(f"/runs/{run_id}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "cancelled"

    client.engine_holder["engine"] = FakeEngine()
    resumed = client.post(f"/runs/{run_id}/resume")
    assert resumed.status_code == 200
    _consume_stream(client, run_id)

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] == "done"
    # Resume must not redo work that already succeeded.
    assert next(p for p in detail["phases"] if p["key"] == "scrape")["attempt"] == 1


def test_rerun_one_phase(client):
    run_id = client.post("/runs", json={}).json()["run_id"]
    _consume_stream(client, run_id)

    r = client.post(f"/runs/{run_id}/phases/score/rerun")
    assert r.status_code == 200
    _consume_stream(client, run_id)

    detail = client.get(f"/runs/{run_id}").json()
    by_key = {p["key"]: p for p in detail["phases"]}
    assert by_key["score"]["attempt"] == 2
    assert by_key["report"]["attempt"] == 2      # downstream was invalidated too
    assert by_key["scrape"]["attempt"] == 1      # upstream was not


def test_rerun_unknown_phase_is_400(client):
    run_id = client.post("/runs", json={}).json()["run_id"]
    _consume_stream(client, run_id)
    assert client.post(f"/runs/{run_id}/phases/bogus/rerun").status_code == 400


def test_partial_phase_selection(client):
    r = client.post("/runs", json={"only": ["scrape"]})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    _consume_stream(client, run_id)
    detail = client.get(f"/runs/{run_id}").json()
    assert [p["key"] for p in detail["phases"]] == ["scrape"]
    assert detail["status"] == "done"


def test_pipeline_config_round_trips_with_defaults(client):
    phases = client.get("/pipeline").json()["phases"]
    assert phases["scrape"] == {"enabled": True, "model": None}
    assert phases["score"] == {"enabled": True, "model": None}

    bad = client.put("/pipeline", json={"phases": {"not-a-real-phase": {"enabled": True}}})
    assert bad.status_code == 400

    saved = client.put("/pipeline", json={
        "phases": {"score": {"enabled": True, "model": "opus"}},
    })
    assert saved.status_code == 200
    assert saved.json()["phases"]["score"] == {"enabled": True, "model": "opus"}
    # Everything else keeps its default — a PUT only touches what it mentions.
    assert saved.json()["phases"]["scrape"] == {"enabled": True, "model": None}


def test_required_phases_cannot_be_disabled_from_a_run(client):
    """None of scrape/score/report are optional in the test pipeline — 'enabled: false'
    on a required phase must not exclude it, or a bad config could silently break the
    whole run instead of just being ignored."""
    client.put("/pipeline", json={"phases": {"scrape": {"enabled": False}}})

    r = client.post("/runs", json={})
    run_id = r.json()["run_id"]
    _consume_stream(client, run_id)
    detail = client.get(f"/runs/{run_id}").json()
    assert [p["key"] for p in detail["phases"]] == ["scrape", "score", "report"]


def test_models_endpoint_lists_claude_code_tiers(client):
    models = client.get("/models?engine=claude_code").json()["models"]
    ids = {m["id"] for m in models}
    assert {"haiku", "sonnet", "opus"} <= ids
    tiers = {m["id"]: m["tier"] for m in models}
    assert tiers["haiku"] == "fast"
    assert tiers["sonnet"] == "reasoning"
    assert tiers["opus"] == "max"


def test_busy_returns_409(client):
    client.engine_holder["engine"] = FakeEngine(delay=30)
    first = client.post("/runs", json={})
    assert first.status_code == 200
    second = client.post("/runs", json={})
    assert second.status_code == 409
    client.post(f"/runs/{first.json()['run_id']}/stop")


def test_missing_run_is_404(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/runs/nope/resume").status_code == 404
    assert client.get("/runs/nope/events").status_code == 404


def test_profile_review_round_trip(client, tmp_path):
    # No profile yet: the endpoint still returns a shape so the form can render.
    empty = client.get("/api/profile").json()
    assert empty["exists"] is False
    assert empty["profile"]["skills"] == []

    sample = {"name": "Ada Lovelace", "email": "ada@example.com", "skills": ["Python"]}
    r = client.put("/api/profile", json={"data": sample})
    assert r.status_code == 200
    assert r.json()["profile"]["name"] == "Ada Lovelace"

    stored = client.get("/api/profile").json()
    assert stored["exists"] is True
    assert stored["profile"]["skills"] == ["Python"]

    assert client.get("/api/profile/done").json()["done"] is False
    assert client.post("/api/profile/done", json={"done": True}).json()["done"] is True
    assert client.get("/api/profile/done").json()["done"] is True
    assert client.post("/api/profile/done", json={"done": False}).json()["done"] is False
