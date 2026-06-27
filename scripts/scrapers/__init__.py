"""Native job-board scrapers — pure Python, NO LLM, NO Apify.

Each module exposes `fetch(keywords, location, max_results, hours_old, focus) -> list[dict]`
returning jobs in the canonical JobPilot schema (see _common.build_job).
"""
