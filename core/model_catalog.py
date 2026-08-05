"""Per-engine model catalog for phase-level model selection.

Each phase declares a `model_tier` ("fast" | "reasoning") in `orchestrator.phases`.
This module resolves that tier to a concrete model id for whichever engine is active —
Claude and Gemini name their models differently, so the tier is the engine-agnostic
concept the UI and the orchestrator actually deal in.

The "max" tier (Opus) is never a tier default for any phase — it costs 5x Sonnet for
work most phases don't need, so it only appears as an explicit, opt-in choice the user
makes per phase, never something a fresh install or a reset pipeline picks by itself.
"""
from __future__ import annotations

# id: what gets passed to the engine (claude_code's --model alias, claude_api's/Agent
# SDK's full model id, gemini's --model flag). label: UI display. tier: which
# Phase.model_tier this satisfies, or "max" for the opt-in-only tier.
CATALOG: dict[str, list[dict]] = {
    "claude_code": [
        {"id": "haiku", "label": "Haiku 4.5", "tier": "fast"},
        {"id": "sonnet", "label": "Sonnet 5", "tier": "reasoning"},
        {"id": "opus", "label": "Opus 5", "tier": "max"},
    ],
    "claude_api": [
        {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5", "tier": "fast"},
        {"id": "claude-sonnet-5", "label": "Sonnet 5", "tier": "reasoning"},
        {"id": "claude-opus-5", "label": "Opus 5", "tier": "max"},
    ],
    "gemini": [
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "tier": "fast"},
        {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "tier": "reasoning"},
    ],
    # No fixed catalog — whatever model the user's own command template runs is up to
    # them; there's no single flag JobPilot can universally override.
    "generic_cli": [],
}


def models_for(engine: str) -> list[dict]:
    """The selectable models for one engine, in catalog order."""
    return CATALOG.get(engine, [])


def default_model(engine: str, tier: str) -> str | None:
    """The preferred model id for a tier on this engine, or None if the engine has no
    fixed catalog (generic_cli) — the caller then falls back to not passing --model at
    all, so nothing overrides the user's own command template."""
    for entry in CATALOG.get(engine, []):
        if entry["tier"] == tier:
            return entry["id"]
    return None


def resolve(engine: str, tier: str, requested: str | None) -> str | None:
    """The model id to actually run with: the user's explicit choice if it's a real
    option for this engine and tier is not locked by the caller, else the tier default."""
    options = {m["id"] for m in models_for(engine)}
    if requested and requested in options:
        return requested
    return default_model(engine, tier)
