"""core.model_catalog — per-engine model options and tier resolution."""
from __future__ import annotations

from core import model_catalog


def test_claude_code_tier_defaults_never_pick_opus():
    """Opus must never be a *tier default* — every Phase.model_tier in the registry is
    "fast" or "reasoning" (see test_orchestrator's registry test), and neither resolves
    to Opus unless the user explicitly picks it for that phase."""
    assert model_catalog.default_model("claude_code", "fast") == "haiku"
    assert model_catalog.default_model("claude_code", "reasoning") == "sonnet"
    assert "opus" not in (
        model_catalog.default_model("claude_code", "fast"),
        model_catalog.default_model("claude_code", "reasoning"),
    )


def test_gemini_catalog_has_its_own_model_ids():
    ids = {m["id"] for m in model_catalog.models_for("gemini")}
    assert ids == {"gemini-2.5-flash", "gemini-2.5-pro"}
    assert model_catalog.default_model("gemini", "fast") == "gemini-2.5-flash"
    assert model_catalog.default_model("gemini", "reasoning") == "gemini-2.5-pro"


def test_generic_cli_has_no_fixed_catalog():
    """No universal --model flag for an arbitrary command template — the caller must
    not pass one, so the user's own template stays in control."""
    assert model_catalog.models_for("generic_cli") == []
    assert model_catalog.default_model("generic_cli", "fast") is None


def test_resolve_prefers_a_valid_explicit_choice():
    assert model_catalog.resolve("claude_code", "reasoning", "opus") == "opus"


def test_resolve_falls_back_to_tier_default_when_unset():
    assert model_catalog.resolve("claude_code", "fast", None) == "haiku"


def test_resolve_falls_back_to_tier_default_for_an_invalid_choice():
    """A stale/garbage value in storage must never propagate to the engine."""
    assert model_catalog.resolve("claude_code", "reasoning", "not-a-real-model") == "sonnet"


def test_resolve_returns_none_for_an_unfixed_catalog():
    assert model_catalog.resolve("generic_cli", "fast", None) is None
