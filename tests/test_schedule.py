"""Schedule slots, catch-up, network retry and the service controls."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    from core import db
    db.dispose()
    db.init_db()

    # Never touch the real systemd/launchd config from a test.
    import install_service
    monkeypatch.setattr(install_service, "is_installed", lambda: False)
    monkeypatch.setattr(install_service, "status", lambda: ["not installed"])
    monkeypatch.setattr(install_service, "install", lambda: True)
    monkeypatch.setattr(install_service, "uninstall", lambda: True)

    import app as app_module
    with TestClient(app_module.app) as c:
        yield c
    db.dispose()


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def test_slot_lifecycle(client):
    body = client.get("/api/schedule").json()
    assert body["slots"] == []
    assert body["service"]["installed"] is False

    created = client.post("/api/schedule/slots",
                          json={"name": "morning", "time": "09:30"}).json()
    assert len(created["slots"]) == 1
    slot = created["slots"][0]
    assert slot["time"] == "09:30"
    assert slot["enabled"] is True

    updated = client.put(f"/api/schedule/slots/{slot['id']}",
                         json={"time": "10:15", "mode": "native"}).json()
    assert updated["slots"][0]["time"] == "10:15"
    assert updated["slots"][0]["mode"] == "native"

    after = client.delete(f"/api/schedule/slots/{slot['id']}").json()
    assert after["slots"] == []


def test_deleting_a_slot_is_possible_at_all(client):
    """v1 had no delete — the only way to remove a slot was to edit preferences.json."""
    slot = client.post("/api/schedule/slots", json={"name": "x", "time": "07:00"}).json()["slots"][0]
    assert client.delete(f"/api/schedule/slots/{slot['id']}").status_code == 200
    assert client.delete(f"/api/schedule/slots/{slot['id']}").status_code == 404


def test_invalid_time_is_rejected(client):
    r = client.post("/api/schedule/slots", json={"name": "bad", "time": "25:99"})
    assert r.status_code == 400
    assert "24-hour" in r.json()["detail"]


def test_duplicate_names_are_disambiguated(client):
    client.post("/api/schedule/slots", json={"name": "daily", "time": "09:00"})
    body = client.post("/api/schedule/slots", json={"name": "daily", "time": "18:00"}).json()
    assert sorted(s["name"] for s in body["slots"]) == ["daily", "daily-2"]


def test_disabled_slots_do_not_get_a_timer(client, monkeypatch):
    import scheduler as scheduler_module

    jobs: list[str] = []
    monkeypatch.setattr(scheduler_module.scheduler, "jobs", lambda: jobs)

    slot = client.post("/api/schedule/slots", json={"name": "s", "time": "09:00"}).json()["slots"][0]
    client.put(f"/api/schedule/slots/{slot['id']}", json={"enabled": False})

    from core.repo import schedule as schedule_repo
    assert schedule_repo.list_all(enabled_only=True) == []


def test_catchup_grace_is_configurable_and_bounded(client):
    assert client.put("/api/schedule/catchup", json={"hours": 12}).status_code == 200
    assert client.get("/api/schedule").json()["catchup_grace_hours"] == 12

    # 0 disables catch-up — a legitimate choice, not an error.
    assert client.put("/api/schedule/catchup", json={"hours": 0}).status_code == 200
    assert client.put("/api/schedule/catchup", json={"hours": 500}).status_code == 400
    assert client.put("/api/schedule/catchup", json={"hours": -1}).status_code == 400


def test_service_install_and_uninstall(client):
    assert client.post("/api/schedule/service/install").json()["ok"] is True
    assert client.post("/api/schedule/service/uninstall").json()["ok"] is True
    assert client.post("/api/schedule/service/nonsense").status_code == 400


# --------------------------------------------------------------------------- #
# Catch-up semantics
# --------------------------------------------------------------------------- #
def test_missed_slot_is_caught_up_once(client):
    from core.repo import schedule as schedule_repo

    schedule_repo.create(name="morning", time="09:30")
    now = datetime(2026, 8, 1, 11, 0, tzinfo=IST)     # 90 minutes after the slot

    due = schedule_repo.missed_since_downtime(grace_hours=6, now=now)
    assert [d["name"] for d in due] == ["morning"]

    # Serving it records the occurrence, not the wall clock — so it can't fire twice.
    schedule_repo.record_fire(due[0]["id"], run_id="r1", when=now)
    assert schedule_repo.missed_since_downtime(grace_hours=6, now=now + timedelta(minutes=5)) == []


def test_a_long_outage_does_not_queue_a_run_per_missed_day(client):
    """A laptop closed for a week must produce one run, not seven."""
    from core.repo import schedule as schedule_repo

    schedule_repo.create(name="morning", time="09:30")
    now = datetime(2026, 8, 8, 11, 0, tzinfo=IST)     # a week later
    due = schedule_repo.missed_since_downtime(grace_hours=6, now=now)
    assert len(due) == 1                              # only the most recent occurrence


def test_a_stale_miss_is_skipped(client):
    from core.repo import schedule as schedule_repo

    schedule_repo.create(name="morning", time="09:30")
    now = datetime(2026, 8, 1, 23, 0, tzinfo=IST)     # 13.5 hours later
    assert schedule_repo.missed_since_downtime(grace_hours=6, now=now) == []


def test_slots_respect_their_own_timezone(client):
    from core.repo import schedule as schedule_repo

    schedule_repo.create(name="ny", time="09:30", timezone="America/New_York")
    # 11:00 IST is 01:30 in New York — the 09:30 NY slot hasn't come round yet today,
    # so the most recent occurrence is yesterday's and long out of grace.
    now = datetime(2026, 8, 1, 11, 0, tzinfo=IST)
    assert schedule_repo.missed_since_downtime(grace_hours=6, now=now) == []


# --------------------------------------------------------------------------- #
# Network retry
# --------------------------------------------------------------------------- #
async def test_no_network_retries_rather_than_failing(client, monkeypatch):
    import asyncio

    import scheduler as scheduler_module
    from core.repo import schedule as schedule_repo

    slot = schedule_repo.create(name="morning", time="09:30")

    attempts = {"n": 0}

    def flaky_network():
        attempts["n"] += 1
        return attempts["n"] > 2          # offline for the first two checks

    started: list[dict] = []

    async def fake_start(**kwargs):
        started.append(kwargs)
        return {"id": "run-1"}

    monkeypatch.setattr(scheduler_module, "has_network", flaky_network)
    monkeypatch.setattr(scheduler_module.manager, "start_run", fake_start)
    monkeypatch.setattr(scheduler_module, "RETRY_LADDER_SECONDS", (0, 0, 0, 0))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", lambda *_a: real_sleep(0))

    await scheduler_module._start(slot, trigger="schedule")

    assert attempts["n"] == 3             # retried, then succeeded
    assert started and started[0]["trigger"] == "schedule"
    assert schedule_repo.get(slot["id"])["last_run_id"] == "run-1"


async def test_a_busy_run_skips_the_slot_instead_of_stacking(client, monkeypatch):
    import scheduler as scheduler_module
    from core.repo import schedule as schedule_repo
    from orchestrator.runner import RunBusyError

    slot = schedule_repo.create(name="morning", time="09:30")

    async def busy(**_kwargs):
        raise RunBusyError("already running")

    monkeypatch.setattr(scheduler_module, "has_network", lambda: True)
    monkeypatch.setattr(scheduler_module.manager, "start_run", busy)

    await scheduler_module._start(slot, trigger="schedule")
    assert "already running" in schedule_repo.get(slot["id"])["last_outcome"]
