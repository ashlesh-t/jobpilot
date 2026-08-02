"""JobPilot core — provider-agnostic domain layer.

Everything that is *not* pipeline logic and *not* transport lives here: filesystem
layout, the database (Postgres in Docker, SQLite fallback), the ORM models, and the
repository functions the server/orchestrator/CLI call.

Layer A scripts (`scripts/apify_scraper.py`, `dedupe.py`, `filter.py`, `scripts/scrapers/*`)
must never import this package in a way that pulls in an LLM — core is pure data.
"""
from __future__ import annotations

__all__ = ["paths", "db", "models"]
