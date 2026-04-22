"""Phase 1.2 — pricing registry."""

from __future__ import annotations

from insightxpert_api.metrics.pricing import (
    PRICING,
    PRICING_VERSION,
    cost_usd,
)


def test_pricing_lookup_by_model_returns_registered_rate() -> None:
    """gemini-2.5-flash — 1M input tokens × $0.30 = $0.30, 1M output × $2.50 = $2.50."""
    cost, version = cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000)
    expected = PRICING["gemini-2.5-flash"].input_per_1m + PRICING["gemini-2.5-flash"].output_per_1m
    assert cost == expected
    assert version == PRICING_VERSION


def test_pricing_stamps_version_even_for_unknown_model() -> None:
    """Unknown models still stamp the current version + fall back to a
    non-zero price so quota math doesn't silently under-count."""
    cost, version = cost_usd("gemini-7.0-fantasy", 1_000_000, 0)
    assert version == PRICING_VERSION
    assert cost > 0.0
