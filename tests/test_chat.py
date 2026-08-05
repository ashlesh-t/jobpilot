"""Assistant — context assembly, history, cost accounting, failure handling."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import signup


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    from core import db
    db.dispose()
    db.init_db()

    import scheduler
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler.scheduler, "shutdown", lambda: None)

    import app as app_module
    with TestClient(app_module.app) as c:
        c.user_id = signup(c)["id"]
        yield c
    db.dispose()


def _seed(user_id):
    from core.repo import applications as applications_repo
    from core.repo import jobs as jobs_repo
    from core.repo import profiles as profiles_repo
    from core.repo import settings as settings_repo

    profiles_repo.save(user_id, {"name": "Ada Lovelace", "skills": ["Go", "Docker"],
                        "experience_years": 2}, verified=True)
    settings_repo.update_preferences(user_id, {"locations": ["Bengaluru"], "role_types": ["Backend"],
                                      "target_ctc_min_lpa": 18})
    jobs_repo.upsert_scored(user_id, [{
        "job_id": "swissre-1", "company": "Swiss Re", "role": "Golang Engineer",
        "location": "Bengaluru", "score": 78, "keyword_score": 80, "semantic_score": 75,
        "matched_skills": ["Go", "Docker"], "missing_skills": ["Kafka"],
        "market_salary": "18-24 LPA", "archetype": "gcc-enterprise",
        "prep_focus": "Deep-dive your resume projects.",
    }])
    applications_repo.mark_applied(user_id, "swissre-1")


class FakeEngine:
    """Captures the prompt so the tests can assert what the assistant was actually told."""
    last_prompt = ""

    def __init__(self, answer="Swiss Re scored 78 because you match 4 of 5 skills.",
                 ok=True, usage=None):
        self.answer = answer
        self.ok = ok
        self.usage = usage

    def available(self):
        return True, ""

    async def run(self, program, run_id, on_event):
        from engines.base import RunResult
        FakeEngine.last_prompt = program
        return RunResult(ok=self.ok, error="" if self.ok else "backend exploded",
                         artifacts={"final_text": self.answer} if self.ok else {},
                         usage=self.usage)

    async def stop(self):
        pass


@pytest.fixture()
def fake_engine(monkeypatch):
    holder = {"engine": FakeEngine()}
    import engines
    monkeypatch.setattr(engines, "get_engine", lambda *a, **k: holder["engine"])
    return holder


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #
def test_context_carries_the_users_real_data(client, fake_engine):
    _seed(client.user_id)
    client.post("/api/chat", json={"message": "Why did Swiss Re score 78?"})

    prompt = FakeEngine.last_prompt
    assert "Ada Lovelace" in prompt
    assert "Swiss Re" in prompt
    assert "Golang Engineer" in prompt
    assert "18-24 LPA" in prompt
    assert "Bengaluru" in prompt          # preferences
    assert "APPLICATIONS: 1" in prompt    # funnel


def test_the_open_job_is_highlighted_in_the_prompt(client, fake_engine):
    _seed(client.user_id)
    client.post("/api/chat", json={"message": "Explain this one",
                                   "job_id": "swissre-1"})
    prompt = FakeEngine.last_prompt
    assert "THE JOB THEY ARE LOOKING AT" in prompt
    assert "gcc-enterprise" in prompt
    assert "Deep-dive your resume projects." in prompt


def test_prompt_explains_the_scoring_model(client, fake_engine):
    """The assistant must be able to explain score vs effective_score correctly."""
    _seed(client.user_id)
    client.post("/api/chat", json={"message": "hi"})
    prompt = FakeEngine.last_prompt
    assert "effective_score" in prompt
    assert "never invent" in prompt.lower()


# --------------------------------------------------------------------------- #
# Conversation
# --------------------------------------------------------------------------- #
def test_history_round_trip_and_clear(client, fake_engine):
    _seed(client.user_id)
    assert client.get("/api/chat").json()["messages"] == []

    body = client.post("/api/chat", json={"message": "Why did Swiss Re score 78?"}).json()
    assert "78" in body["answer"]

    messages = client.get("/api/chat").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]

    assert client.delete("/api/chat").json()["messages"] == []
    assert client.get("/api/chat").json()["messages"] == []


def test_earlier_turns_are_carried_forward(client, fake_engine):
    _seed(client.user_id)
    client.post("/api/chat", json={"message": "First question"})
    client.post("/api/chat", json={"message": "And a follow-up"})
    assert "First question" in FakeEngine.last_prompt


def test_conversations_are_separate(client, fake_engine):
    _seed(client.user_id)
    client.post("/api/chat", json={"message": "one", "conversation_id": "a"})
    client.post("/api/chat", json={"message": "two", "conversation_id": "b"})
    assert len(client.get("/api/chat?conversation_id=a").json()["messages"]) == 2
    assert len(client.get("/api/chat?conversation_id=b").json()["messages"]) == 2


def test_empty_message_is_rejected(client, fake_engine):
    assert client.post("/api/chat", json={"message": "   "}).status_code == 400


# --------------------------------------------------------------------------- #
# Cost and failures
# --------------------------------------------------------------------------- #
def test_each_answer_is_billed_to_the_cost_ledger(client, fake_engine):
    from engines.base import Usage
    from core.repo import cost as cost_repo

    _seed(client.user_id)
    fake_engine["engine"] = FakeEngine(
        usage=Usage(tokens_in=2000, tokens_out=400, model="claude-opus-5",
                    source="metered"))

    body = client.post("/api/chat", json={"message": "hello"}).json()
    assert body["usd"] > 0

    summary = cost_repo.summary(client.user_id, window="month")
    assert summary["usd"] > 0
    assert any(k["kind"] == "chat" for k in summary["by_kind"])


def test_backend_failure_is_reported_not_swallowed(client, fake_engine):
    _seed(client.user_id)
    fake_engine["engine"] = FakeEngine(ok=False)
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 502
    assert "exploded" in r.json()["detail"]


def test_unavailable_backend_says_so(client, monkeypatch):
    import engines

    class Unavailable:
        def available(self):
            return False, "not logged in"

    monkeypatch.setattr(engines, "get_engine", lambda *a, **k: Unavailable())
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 503
    assert "not logged in" in r.json()["detail"]


def test_context_survives_an_empty_database(client, fake_engine):
    """A brand-new install must still be able to hold a conversation."""
    r = client.post("/api/chat", json={"message": "what can you do?"})
    assert r.status_code == 200
    assert "not built yet" in FakeEngine.last_prompt
