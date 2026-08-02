"""Repository layer — every database query lives here, none in server/ or orchestrator/.

Each module owns one aggregate and exposes plain functions that take/return dicts or
ORM objects. Callers never build queries themselves, so schema changes stay contained.
"""
from __future__ import annotations

from . import (  # noqa: F401
    applications,
    cost,
    jobs,
    profiles,
    resumes,
    runs,
    schedule,
    settings,
    tailored,
)

__all__ = [
    "applications", "cost", "jobs", "profiles", "resumes",
    "runs", "schedule", "settings", "tailored",
]
