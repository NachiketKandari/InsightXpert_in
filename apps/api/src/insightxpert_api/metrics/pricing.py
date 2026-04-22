"""Gemini pricing registry — USD per 1M tokens.

Phase 1.2 (spend/quota) — each row in ``query_metrics`` stamps the
``pricing_version`` used to compute ``cost_usd`` so historic rows stay truthful
when prices change. A pricing change = new entry with a bumped
``PRICING_VERSION`` constant; the old entries may remain in a follow-up
dated registry if we need reprice-as-of-X analytics.

!!! TO-CONFIRM
    Prices below are best-known values as of 2026-04-24 from Google's public
    Gemini pricing page. Lock these before shipping to paid tiers.

    Known ambiguities:
      * gemini-2.5-flash       — $0.30 in / $2.50 out per 1M (standard)
      * gemini-3.1-flash-lite-preview — NOT YET PUBLISHED; using conservative
        placeholders ($0.10 in / $0.40 out per 1M) based on "lite tier is
        typically ~3× cheaper than flash" heuristic.
      * gemini-embedding-001   — $0.15 in per 1M (output is vector, no token cost).

    Update the ``PRICING`` dict and bump ``PRICING_VERSION`` when Google
    publishes final numbers. Historic rows keep their old pricing_version
    so cost_usd remains accurate against the table they were emitted under.
"""

from __future__ import annotations

from dataclasses import dataclass

# Bump on any pricing change. Stamped on every query_metrics row.
PRICING_VERSION = "2026-04-24-v1"


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1 million tokens (input, output)."""

    input_per_1m: float
    output_per_1m: float


# Lower-cased model keys. Lookups are case-insensitive (see ``cost_usd``).
PRICING: dict[str, ModelPricing] = {
    # Gemini 2.5 Flash — current production chat model (config.py default).
    # $0.30 / $2.50 per 1M. TO-CONFIRM.
    "gemini-2.5-flash": ModelPricing(input_per_1m=0.30, output_per_1m=2.50),
    # Gemini 3.1 Flash Lite Preview — near-future cheaper tier. Placeholder
    # pricing, CONFIRM BEFORE SHIP. We use conservative values (3× cheaper
    # than flash) so cost_usd is a slight over-estimate rather than under.
    "gemini-3.1-flash-lite-preview": ModelPricing(
        input_per_1m=0.10, output_per_1m=0.40
    ),
    # Embeddings — input only. Output is a vector, not billable tokens.
    "gemini-embedding-001": ModelPricing(input_per_1m=0.15, output_per_1m=0.0),
}

# Fallback when a model isn't in the registry — keeps cost tracking from
# silently dropping to $0 for an unknown model. Chosen to match flash so we
# don't under-count spend on an unlisted new model.
_FALLBACK_PRICING = ModelPricing(input_per_1m=0.30, output_per_1m=2.50)


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> tuple[float, str]:
    """Return ``(cost_usd, pricing_version)`` for a token count.

    Case-insensitive model lookup. Unknown models fall back to Gemini flash
    pricing and still return the current ``PRICING_VERSION`` — the row will
    carry a best-effort cost rather than NULL, which matters for quota math.
    """
    key = (model or "").lower()
    p = PRICING.get(key, _FALLBACK_PRICING)
    cost = (
        (tokens_in / 1_000_000.0) * p.input_per_1m
        + (tokens_out / 1_000_000.0) * p.output_per_1m
    )
    return float(cost), PRICING_VERSION


__all__ = ["PRICING", "PRICING_VERSION", "ModelPricing", "cost_usd"]
