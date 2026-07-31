"""HTTP + SSE integration test — drives the real FastAPI app with a fake engine.

Verifies the whole request path (POST /runs -> SSE stream -> artifacts) without a real
LLM, plus that the read endpoints return sane payloads.
"""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import run_manager
from engines.base import RunEvent, RunResult


class FakeEngine:
    name = "fake"; label = "Fake"; metered = False

    def available(self):
        return True, ""

    async def run(self, program, run_id, on_event):
        run_dir = Path(f"/tmp/jobpilot_run_{run_id}")
        with (run_dir / "events.jsonl").open("a") as fh:
            fh.write(json.dumps({"stage": "scrape", "status": "done",
                                 "msg": "42 raw", "data": {"total": 42,
                                 "source": "internshala", "count": 20}}) + "\n")
        await asyncio.sleep(0.4)
        on_event(RunEvent("score", "done", "scored 8", data={"n": 8}))
        on_event(RunEvent("notify", "done", "digest sent"))
        return RunResult(ok=True, artifacts={"final_text": "Top: Acme SDE (81)"})


@pytest.fixture
def client(monkeypatch):
    # neutralize the scheduler so TestClient lifespan doesn't touch APScheduler
    import scheduler
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler.scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(run_manager.engines, "get_engine", lambda name=None, **k: FakeEngine())
    import app as app_module
    with TestClient(app_module.app) as c:
        yield c


def test_read_endpoints(client):
    assert client.get("/health").json()["ok"] is True
    assert "engines" in client.get("/engines").json()
    assert "rows" in client.get("/doctor").json()
    assert "slots" in client.get("/schedule").json()
    assert "engine" in client.get("/config").json()


def test_run_and_sse_stream(client):
    r = client.post("/runs", json={"mode": "native", "engine": "fake"})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    stages = set()
    with client.stream("GET", f"/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
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
            if ev.get("stage") == "done" and ev.get("origin") == "manager":
                break

    assert ("scrape", "done") in stages     # Layer A via events.jsonl tail
    assert ("score", "done") in stages       # Layer B via engine
    assert ("notify", "done") in stages

    # artifacts available after completion
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] == "done"


def test_profile_review_round_trip(client, monkeypatch, tmp_path):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))

    # No profile yet -> 404
    assert client.get("/api/profile").status_code == 404

    sample = {"name": "Ada Lovelace", "email": "ada@example.com", "skills": ["Python"]}
    r = client.post("/api/profile", json=sample)
    assert r.status_code == 200
    assert r.json()["profile"] == sample

    r = client.get("/api/profile")
    assert r.status_code == 200
    assert r.json() == sample

    # profile-review page is served
    assert client.get("/profile-review").status_code == 200

    # done flag starts false, flips true, and can be cleared
    assert client.get("/api/profile/done").json()["done"] is False
    assert client.post("/api/profile/done", json={"done": True}).json()["done"] is True
    assert client.get("/api/profile/done").json()["done"] is True
    assert client.post("/api/profile/done", json={"done": False}).json()["done"] is False
    assert client.get("/api/profile/done").json()["done"] is False


def test_busy_returns_409(client, monkeypatch):
    # make the fake run long enough to overlap
    slow = FakeEngine()

    async def slow_run(program, run_id, on_event):
        await asyncio.sleep(1.0)
        return RunResult(ok=True)
    monkeypatch.setattr(slow, "run", slow_run)
    monkeypatch.setattr(run_manager.engines, "get_engine", lambda name=None, **k: slow)

    first = client.post("/runs", json={"mode": "native", "engine": "fake"})
    assert first.status_code == 200
    second = client.post("/runs", json={"mode": "native", "engine": "fake"})
    assert second.status_code == 409
