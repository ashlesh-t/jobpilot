"""Settings / preferences repository.

The `settings` table is authoritative. `options/preferences.json` is still written on
every change because the Layer A scripts (`apify_scraper.py`, `filter.py`, `dedupe.py`,
`report_generator.py`, `telegram_notify.py`) read that file directly and must keep
working unchanged — that is the Layer A invariant in practice.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..db import session_scope
from ..models import Setting
from ..paths import ensure_dirs, prefs_path

REPO_DIR = Path(__file__).resolve().parents[2]
EXAMPLE_PREFS = REPO_DIR / "config" / "preferences.example.json"

# Keys that make up preferences.json. Anything else in `settings` is service config
# (database url, engine choice, UI state) and is deliberately not exported.
PREFERENCE_KEYS = (
    "name", "email", "locations", "location_priority", "remote_ok", "job_market_focus",
    "search_keywords_extra", "target_ctc_min_lpa", "role_types", "experience_years",
    "degree", "graduation", "availability_date", "notice_period_days", "preferred_stack",
    "naukri_profile_url", "linkedin_profile_url", "resume_path", "resume_hash",
    "score_threshold", "top_n_tailor", "top_n_report", "hn_max_results", "per_source_cap",
    "schedule_slots_ist", "engine", "notify_channels", "stale_after_days",
)

DEFAULTS: dict[str, Any] = {
    "name": "",
    "email": "",
    "locations": [],
    "location_priority": [],
    "remote_ok": True,
    "job_market_focus": "india",
    "search_keywords_extra": "",
    "target_ctc_min_lpa": 0,
    "role_types": [],
    "experience_years": 0,
    "degree": "",
    "graduation": "",
    "availability_date": "",
    "notice_period_days": 0,
    "preferred_stack": [],
    "naukri_profile_url": "",
    "linkedin_profile_url": "",
    "resume_path": "",
    "resume_hash": "",
    "score_threshold": 65,
    "top_n_tailor": 5,
    "top_n_report": 50,
    "hn_max_results": 100,
    "per_source_cap": 20,
    "schedule_slots_ist": [],
    "engine": {"provider": "claude_code", "model": "", "permission_mode": "bypassPermissions"},
    "notify_channels": ["telegram"],
    "stale_after_days": 21,
    "setup_complete": False,
}


def _example_defaults() -> dict[str, Any]:
    try:
        return json.loads(EXAMPLE_PREFS.read_text())
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Raw key/value access
# --------------------------------------------------------------------------- #
def get(key: str, default: Any = None) -> Any:
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            if default is not None:
                return default
            return DEFAULTS.get(key, _example_defaults().get(key))
        return row.value


def set(key: str, value: Any, *, export: bool = True) -> None:  # noqa: A001
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value
    if export and key in PREFERENCE_KEYS:
        export_preferences()


def set_many(values: dict[str, Any], *, export: bool = True) -> None:
    with session_scope() as s:
        for key, value in values.items():
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=value))
            else:
                row.value = value
    if export and any(k in PREFERENCE_KEYS for k in values):
        export_preferences()


def all() -> dict[str, Any]:  # noqa: A001
    with session_scope() as s:
        return {r.key: r.value for r in s.scalars(select(Setting)).all()}


def delete(key: str) -> None:
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is not None:
            s.delete(row)


# --------------------------------------------------------------------------- #
# Preferences facade
# --------------------------------------------------------------------------- #
def preferences() -> dict[str, Any]:
    """Full preferences dict: example defaults < built-in defaults < stored values."""
    merged: dict[str, Any] = {}
    merged.update(_example_defaults())
    merged.update(DEFAULTS)
    stored = all()
    for key in PREFERENCE_KEYS:
        if key in stored:
            merged[key] = stored[key]
    return {k: merged[k] for k in PREFERENCE_KEYS if k in merged}


def update_preferences(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge-write only the recognized preference keys, then re-export the JSON file."""
    clean = {k: v for k, v in patch.items() if k in PREFERENCE_KEYS}
    if clean:
        set_many(clean)
    return preferences()


def export_preferences() -> Path:
    """Write options/preferences.json for the Layer A scripts (read-before-write)."""
    ensure_dirs()
    path = prefs_path()
    current: dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text())
        except Exception:
            current = {}
    current.update(preferences())
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False))
    return path


def is_setup_complete() -> bool:
    return bool(get("setup_complete", False))


def mark_setup_complete(value: bool = True) -> None:
    set("setup_complete", value, export=False)


def engine_config() -> dict[str, Any]:
    """The engine block, with defaults filled in."""
    eng = get("engine") or {}
    if not isinstance(eng, dict):
        eng = {}
    return {
        "provider": eng.get("provider", "claude_code"),
        "model": eng.get("model", ""),
        "permission_mode": eng.get("permission_mode", "bypassPermissions"),
        "command_template": eng.get("command_template", ""),
    }


def pipeline_phase_config() -> dict[str, dict]:
    """Every phase's {enabled, model}, defaults filled in from the phase registry.

    `enabled` only matters for optional phases — the run selection always forces
    required ones on regardless of what's stored (see `enabled_phase_keys`).
    `model` is None unless the user picked one; the orchestrator then falls back to the
    phase's tier default for whichever engine is active (see core.model_catalog).
    """
    from orchestrator import phases as P

    stored = get("pipeline_phase_config", {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    out: dict[str, dict] = {}
    for phase in P.PHASES:
        entry = stored.get(phase.key)
        entry = entry if isinstance(entry, dict) else {}
        out[phase.key] = {
            "enabled": bool(entry.get("enabled", True)),
            "model": entry.get("model") if phase.kind == "llm" else None,
        }
    return out


def set_pipeline_phase_config(config: dict[str, dict]) -> dict[str, dict]:
    """Validate and persist the pipeline editor's choices."""
    from orchestrator import phases as P

    valid_keys = {p.key for p in P.PHASES}
    unknown = config.keys() - valid_keys  # `set` is shadowed by this module's own set()
    if unknown:
        raise ValueError(f"unknown phase(s): {', '.join(sorted(unknown))}")

    cleaned: dict[str, dict] = {}
    for key, entry in config.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{key}: expected an object with enabled/model")
        cleaned[key] = {
            "enabled": bool(entry.get("enabled", True)),
            "model": (entry.get("model") or None),
        }
    set("pipeline_phase_config", cleaned, export=False)
    return pipeline_phase_config()


def enabled_phase_keys() -> list[str]:
    """The phase keys a run should include: every required phase, plus whichever
    optional ones the pipeline editor left enabled."""
    from orchestrator import phases as P

    cfg = pipeline_phase_config()
    return [p.key for p in P.PHASES if not p.optional or cfg[p.key]["enabled"]]
