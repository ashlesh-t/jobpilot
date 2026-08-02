"""The `jobpilot setup` terminal UI.

A guided, resumable wizard: every step writes its result immediately, so Ctrl-C never
loses work and re-running picks up where you left off. Rich handles presentation,
questionary handles interaction; both are optional at import time so `jobpilot --version`
still works in a minimal environment.
"""
from __future__ import annotations

from .wizard import run_setup

__all__ = ["run_setup"]
