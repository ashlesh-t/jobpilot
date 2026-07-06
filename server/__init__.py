"""JobPilot local service package.

Wires sys.path so the flat intra-package imports (`from common import ...`) and the
repo-level imports (`engines`, `scripts/notify`, `secrets`) resolve whether the app is
started via `python -m server` or `uvicorn server.app:app`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _p in (str(_here.parent), str(_here.parent / "scripts"), str(_here)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
