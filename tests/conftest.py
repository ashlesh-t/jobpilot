"""Pytest path wiring — make repo packages importable without an install step."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for p in (REPO, REPO / "scripts", REPO / "scripts" / "scrapers", REPO / "server"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


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
