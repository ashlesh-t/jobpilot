"""JobPilot's phase orchestrator.

A run is a sequence of independently executable phases rather than one opaque LLM call.
Each phase reads named input artifacts, writes one output artifact, and records its
status — which is what makes stop, resume, and per-phase rerun possible.

    phases.py     the phase registry: what runs, in what order, by whom
    artifacts.py  run-scoped artifact storage under <jobpilot_dir>/runs/<run_id>/
    runner.py     executes the sequence; owns cancellation and retries
"""
from __future__ import annotations

__all__ = ["phases", "artifacts", "runner"]
