"""Tests for the auto-mode router (services/mode_router).

The 10 sample-question table is marked ``@pytest.mark.gemini`` because it
spends real LLM calls; CI without a GEMINI_API_KEY will skip it. The
parse-error fallback is a unit test (no live calls) and runs everywhere.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from insightxpert_api.config import get_settings
from insightxpert_api.services import mode_router as mod


@pytest.fixture(autouse=True)
def _reset_router_clients() -> None:
    """Discard cached HTTP clients so each test starts with a clean slate."""
    mod._reset_mode_router_clients()


# Live-call expectations: (question, expected_mode).
# Curated to cover the BASIC / AGENTIC boundary cases called out in the prompt.
SAMPLES: list[tuple[str, str]] = [
    ("show me top 10 users by spend", "basic"),
    ("list all tables", "basic"),
    ("why did revenue drop in Q3", "agentic"),
    ("compare conversion rates between desktop and mobile", "agentic"),
    ("what's the average order value", "basic"),
    ("tell me about this database", "agentic"),
    ("count of customers in California", "basic"),
    ("explain the relationship between orders and users", "agentic"),
    ("how many products are in the catalog", "basic"),
    ("which segment drove the biggest growth and why", "agentic"),
]


@pytest.mark.gemini
@pytest.mark.parametrize("question,expected", SAMPLES)
async def test_classify_mode_live(question: str, expected: str) -> None:
    """Live Gemini call — skipped in CI without a real key.

    The autouse ``_env`` fixture sets ``GEMINI_API_KEY=test-key`` for every
    test, so we gate on the dedicated ``GEMINI_API_KEY_REAL`` env var (also
    referenced by the ``slow`` marker in pyproject.toml). Run via:
    ``GEMINI_API_KEY=$GEMINI_API_KEY_REAL pytest -m gemini ...``.
    """
    real_key = os.environ.get("GEMINI_API_KEY_REAL")
    if not real_key:
        pytest.skip("GEMINI_API_KEY_REAL not set; live router test skipped")
    monkeypatch_key = pytest.MonkeyPatch()
    monkeypatch_key.setenv("GEMINI_API_KEY", real_key)
    from insightxpert_api.config import get_settings as _gs
    _gs.cache_clear()
    settings = _gs()
    decision = await mod.classify_mode(
        question=question,
        db_id="california_schools",
        settings=settings,
    )
    assert decision.mode in ("basic", "agentic")
    assert decision.reason
    # Soft-assert: print mismatch for diagnostics, fail only on the strict run.
    if decision.mode != expected:
        pytest.fail(
            f"router mismatch: q={question!r} got={decision.mode!r} "
            f"expected={expected!r} reason={decision.reason!r}"
        )


async def test_classify_mode_parse_error_falls_back_to_agentic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock the Gemini client to return malformed JSON; assert agentic fallback."""
    fake_response = MagicMock()
    fake_response.text = "this is not json {bad"

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with patch.object(mod.genai, "Client", return_value=fake_client):
        settings = get_settings()
        decision = await mod.classify_mode(
            question="why did revenue drop",
            db_id="california_schools",
            settings=settings,
        )

    assert decision.mode == "agentic"
    assert "fallback" in decision.reason.lower()


async def test_classify_mode_invalid_mode_value_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM returned valid JSON but a mode value outside {basic, agentic}."""
    fake_response = MagicMock()
    fake_response.text = '{"mode": "deep_think", "reason": "made up"}'

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with patch.object(mod.genai, "Client", return_value=fake_client):
        settings = get_settings()
        decision = await mod.classify_mode(
            question="show top 10",
            db_id="x",
            settings=settings,
        )

    assert decision.mode == "agentic"
    assert "fallback" in decision.reason.lower()


async def test_classify_mode_api_error_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network/SDK exception inside generate_content → agentic fallback."""
    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(
        side_effect=RuntimeError("connection reset")
    )

    with patch.object(mod.genai, "Client", return_value=fake_client):
        settings = get_settings()
        decision = await mod.classify_mode(
            question="anything", db_id="x", settings=settings,
        )

    assert decision.mode == "agentic"
    assert "fallback" in decision.reason.lower()


async def test_classify_mode_happy_path_parses_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal JSON response is parsed into a RouteDecision."""
    fake_response = MagicMock()
    fake_response.text = '{"mode": "basic", "reason": "single SELECT"}'

    fake_client = MagicMock()
    fake_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with patch.object(mod.genai, "Client", return_value=fake_client):
        settings = get_settings()
        decision = await mod.classify_mode(
            question="top 10 by spend", db_id="x", settings=settings,
        )

    assert decision.mode == "basic"
    assert decision.reason == "single SELECT"
