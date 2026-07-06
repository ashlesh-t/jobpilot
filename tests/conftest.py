"""Pytest path wiring — make repo packages importable without an install step."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (REPO, REPO / "scripts", REPO / "scripts" / "scrapers", REPO / "server"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
