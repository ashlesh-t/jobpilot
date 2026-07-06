"""GeminiEngine — provider-ready stub for Google Gemini / Antigravity.

Implements the RunEngine interface so the rest of the system (RunManager, setup UI,
config) treats Gemini as a first-class option, but is not wired to a backend yet
(per the "Claude-first, Gemini-ready" decision).

Two realistic integration paths for whoever implements this next:

  1. gemini-cli subprocess — mirror engines/claude_code.py: shell out to `gemini` with a
     streaming/agent mode and normalize its tool-call stream into RunEvents. Antigravity
     (Google's agentic surface) is reachable the same way where a CLI is exposed.
  2. google-genai SDK function-calling loop — mirror engines/claude_api.py: load the
     SKILL.md body as the system instruction, declare Bash/Read/Write/WebSearch/WebFetch
     as function tools, and run the tool-use loop yourself, emitting RunEvents per call.

Either way the SKILL.md program stays the single source of truth; only the transport and
message normalization differ.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from .base import EventCB, RunEngine, RunEvent, RunResult  # noqa: E402


class GeminiEngine(RunEngine):
    name = "gemini"
    label = "Google Gemini / Antigravity (coming soon)"
    metered = True

    def available(self) -> tuple[bool, str]:
        try:
            from jp_secrets import get_secret_optional  # noqa
        except Exception:
            return False, "secrets loader unavailable"
        if not get_secret_optional("GEMINI_API_KEY"):
            return False, "not configured — set GEMINI_API_KEY (backend not yet implemented)"
        # Even with a key, the backend is not built yet — report unavailable, honestly.
        return False, "Gemini backend not implemented yet (interface-ready)"

    async def run(self, program: str, run_id: str, on_event: EventCB) -> RunResult:
        reason = "Gemini engine is not implemented yet — choose Claude Code or Anthropic API"
        on_event(RunEvent("done", "error", reason, origin="engine"))
        return RunResult(ok=False, error=reason)
