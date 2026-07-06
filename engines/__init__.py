"""Engine registry — provider adapter factory + availability listing.

Usage:
    from engines import get_engine, list_engines
    engine = get_engine("claude_code")
    for info in list_engines():
        print(info["name"], info["available"], info["reason"])
"""
from __future__ import annotations

from .base import RunEngine  # noqa: E402
from .claude_code import ClaudeCodeEngine  # noqa: E402
from .claude_api import ClaudeApiEngine  # noqa: E402
from .gemini import GeminiEngine  # noqa: E402

_REGISTRY = {
    ClaudeCodeEngine.name: ClaudeCodeEngine,
    ClaudeApiEngine.name: ClaudeApiEngine,
    GeminiEngine.name: GeminiEngine,
}

DEFAULT_ENGINE = ClaudeCodeEngine.name


def get_engine(name: str | None = None, **kwargs) -> RunEngine:
    """Instantiate an engine by name. Falls back to the default engine."""
    cls = _REGISTRY.get((name or DEFAULT_ENGINE).lower())
    if cls is None:
        raise ValueError(f"unknown engine '{name}'. Options: {sorted(_REGISTRY)}")
    return cls(**kwargs)


def list_engines() -> list[dict]:
    """Availability + metadata for every registered engine (drives the setup UI)."""
    out = []
    for name, cls in _REGISTRY.items():
        eng = cls()
        ok, reason = eng.available()
        out.append({
            "name": name,
            "label": eng.label,
            "metered": eng.metered,
            "available": ok,
            "reason": reason,
        })
    return out


__all__ = ["get_engine", "list_engines", "RunEngine", "DEFAULT_ENGINE"]
