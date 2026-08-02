"""Model pricing — turns token counts into dollars for the cost meter.

Rates are USD per **million** tokens, matching how Anthropic publishes them. They are
editable from Settings (stored under the `pricing_overrides` setting) so a price change
never requires a JobPilot release.

Cache multipliers follow the published prompt-caching economics: a cache read costs
~0.1× the base input rate, a 5-minute cache write ~1.25×.
"""
from __future__ import annotations

from dataclasses import dataclass

CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    label: str = ""


# Rates as of 2026-08. Sonnet 5 lists at $3/$15; the $2/$10 introductory rate runs
# through 2026-08-31, so this table uses the list price and under-promises savings
# rather than under-reporting spend.
PRICES: dict[str, Price] = {
    "claude-fable-5": Price(10.0, 50.0, "Claude Fable 5"),
    "claude-mythos-5": Price(10.0, 50.0, "Claude Mythos 5"),
    "claude-opus-5": Price(5.0, 25.0, "Claude Opus 5"),
    "claude-opus-4-8": Price(5.0, 25.0, "Claude Opus 4.8"),
    "claude-opus-4-7": Price(5.0, 25.0, "Claude Opus 4.7"),
    "claude-opus-4-6": Price(5.0, 25.0, "Claude Opus 4.6"),
    "claude-sonnet-5": Price(3.0, 15.0, "Claude Sonnet 5"),
    "claude-sonnet-4-6": Price(3.0, 15.0, "Claude Sonnet 4.6"),
    "claude-haiku-4-5": Price(1.0, 5.0, "Claude Haiku 4.5"),
}

# Used when the provider reports a model we have no rate for. Opus-tier is the
# conservative choice: over-reporting cost is a far better failure than under-reporting.
FALLBACK = Price(5.0, 25.0, "unknown model (billed at Opus rates)")

# Non-Claude backends. Rates vary by tier and change often, so they default to zero
# and are surfaced as "not priced" rather than guessed at.
NON_CLAUDE_DEFAULT = Price(0.0, 0.0, "not priced")


def _overrides() -> dict[str, dict]:
    try:
        from .repo import settings as settings_repo
        raw = settings_repo.get("pricing_overrides") or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def normalize(model: str) -> str:
    """Strip a date suffix so `claude-opus-5-20260101` prices as `claude-opus-5`."""
    model = (model or "").strip().lower()
    if not model:
        return ""
    # Provider prefixes: Bedrock uses `anthropic.claude-…`
    if "." in model and model.split(".", 1)[0] in ("anthropic", "us", "eu"):
        model = model.split(".", 1)[1]
    if model in PRICES:
        return model
    for known in PRICES:
        if model.startswith(known):
            return known
    return model


def price_for(model: str) -> Price:
    key = normalize(model)
    override = _overrides().get(key)
    if isinstance(override, dict):
        try:
            return Price(float(override["input_per_mtok"]),
                         float(override["output_per_mtok"]),
                         override.get("label", key))
        except (KeyError, TypeError, ValueError):
            pass
    if key in PRICES:
        return PRICES[key]
    if key.startswith("claude"):
        return FALLBACK
    return NON_CLAUDE_DEFAULT


def estimate(*, model: str, tokens_in: int = 0, tokens_out: int = 0,
             cache_read: int = 0, cache_write: int = 0) -> float:
    """USD for one call. Cache reads/writes are priced off the input rate."""
    p = price_for(model)
    if p.input_per_mtok == 0 and p.output_per_mtok == 0:
        return 0.0
    per_token_in = p.input_per_mtok / 1_000_000
    per_token_out = p.output_per_mtok / 1_000_000
    total = (
        tokens_in * per_token_in
        + tokens_out * per_token_out
        + cache_read * per_token_in * CACHE_READ_MULTIPLIER
        + cache_write * per_token_in * CACHE_WRITE_MULTIPLIER
    )
    return round(total, 6)


def price_usage(usage, *, engine: str = "") -> tuple[float, str]:
    """Cost + accounting source for an `engines.base.Usage`.

    A Claude Code subscription run reports real tokens with no marginal dollar cost, so
    it is priced at 0 and labelled `subscription` — the UI shows the tokens without
    implying the user was billed per token.
    """
    source = getattr(usage, "source", "estimated") or "estimated"
    if source == "subscription":
        return 0.0, "subscription"

    reported = getattr(usage, "usd", None)
    if isinstance(reported, (int, float)) and reported > 0:
        return round(float(reported), 6), "metered"

    usd = estimate(
        model=getattr(usage, "model", "") or "",
        tokens_in=getattr(usage, "tokens_in", 0) or 0,
        tokens_out=getattr(usage, "tokens_out", 0) or 0,
        cache_read=getattr(usage, "cache_read", 0) or 0,
        cache_write=getattr(usage, "cache_write", 0) or 0,
    )
    return usd, ("metered" if source == "metered" else "estimated")


def table() -> list[dict]:
    """The editable rate table the Settings page renders."""
    overrides = _overrides()
    rows = []
    for key, p in PRICES.items():
        effective = price_for(key)
        rows.append({
            "model": key,
            "label": p.label,
            "input_per_mtok": effective.input_per_mtok,
            "output_per_mtok": effective.output_per_mtok,
            "overridden": key in overrides,
        })
    return rows
