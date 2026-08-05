"""Pytest path wiring — make repo packages importable without an install step."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for p in (REPO, REPO / "scripts", REPO / "scripts" / "scrapers", REPO / "server"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


def signup(client, username="tester", password="testpass123", email=None):
    """Sign up a fresh account on `client` and return the created user dict.

    Every route in server/ now requires a session cookie (`Depends(get_current_user)`
    in server/auth.py). `TestClient`/httpx persist cookies across calls on the same
    client instance, so signing up once here authenticates every subsequent request
    the test makes with `client` — no separate login step needed.
    """
    resp = client.post("/api/auth/signup", json={
        "username": username, "password": password, "email": email,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def pytest_configure(config):
    """Fail fast if pytest-asyncio is missing.

    A third of the orchestrator and scheduler suite is async. Without the plugin those
    tests don't error in an obvious way — they report "async def functions are not
    natively supported", which is easy to read past in a long CI log while the run
    still looks mostly green. Better to refuse to start.
    """
    if not config.pluginmanager.hasplugin("asyncio"):
        raise pytest.UsageError(
            "pytest-asyncio is not installed — the async orchestrator and scheduler "
            "tests would not run. Install it with:  pip install pytest-asyncio"
        )
