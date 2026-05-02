"""Verify _preflight_concurrent races all 3 tasks via TaskGroup and
tolerates per-task failures without cancelling the others."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_preflight_runs_three_tasks_in_parallel(monkeypatch):
    """Wall time should be ~max of the three task durations, not the sum."""
    from insightxpert_api.routes import chat as chat_route

    async def slow_profile(*a, **kw):
        await asyncio.sleep(0.30)
        return "PROFILE"

    async def slow_classify(*a, **kw):
        await asyncio.sleep(0.30)
        return "DECISION"

    async def slow_fewshot_inner(*a, **kw):
        await asyncio.sleep(0.30)
        # Return a minimal FewShotExample-shaped object the route uses
        return SimpleNamespace(
            question="q", gold_sql="SELECT 1", similarity=0.5, db_id="db1"
        )

    fake_svc = SimpleNamespace(is_active=True, db_ids={"db1"})
    monkeypatch.setattr(chat_route, "get_few_shot_service", lambda: fake_svc)
    monkeypatch.setattr(chat_route, "prefetch_profile", slow_profile)
    monkeypatch.setattr(chat_route, "_resolve_auto_mode", slow_classify)
    monkeypatch.setattr(chat_route, "prefetch_few_shot_example", slow_fewshot_inner)

    # Patch out GeminiLLM construction inside _safe_fewshot — its import
    # is local to the function so reach into the module that owns it.
    from insightxpert_api.llm import gemini as gemini_mod

    class _FakeLLM:
        def __init__(self, **_kw): pass
    monkeypatch.setattr(gemini_mod, "GeminiLLM", _FakeLLM)

    # Patch out ProfileService construction (it pulls the cache singleton —
    # cheap, but irrelevant to this test).
    monkeypatch.setattr(chat_route, "ProfileService", lambda store=None: object())
    monkeypatch.setattr(chat_route, "build_store", lambda s: None)

    body = SimpleNamespace(db_id="db1", message="q", agent_mode="auto")
    cu = SimpleNamespace(id="u1")
    settings = SimpleNamespace(
        gemini_api_key="x",
        gemini_chat_model="m",
        gemini_embed_model="e",
    )

    t0 = asyncio.get_event_loop().time()
    decision, profile, fewshot = await chat_route._preflight_concurrent(
        body, cu, settings, None, None
    )
    elapsed = asyncio.get_event_loop().time() - t0

    assert decision == "DECISION"
    assert profile == "PROFILE"
    assert fewshot is not None and fewshot.db_id == "db1"
    # Wall time should be ~0.30s, not ~0.90s. Allow generous slack for
    # scheduler jitter.
    assert elapsed < 0.55, f"preflight serialized: took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_preflight_tolerates_individual_task_failures(monkeypatch):
    """Failing few-shot retrieval must not cancel profile or auto-mode."""
    from insightxpert_api.routes import chat as chat_route

    async def ok_profile(*a, **kw):
        return "PROFILE"

    async def ok_classify(*a, **kw):
        return "DECISION"

    async def boom_fewshot(*a, **kw):
        raise RuntimeError("embed API down")

    fake_svc = SimpleNamespace(is_active=True, db_ids={"db1"})
    monkeypatch.setattr(chat_route, "get_few_shot_service", lambda: fake_svc)
    monkeypatch.setattr(chat_route, "prefetch_profile", ok_profile)
    monkeypatch.setattr(chat_route, "_resolve_auto_mode", ok_classify)
    monkeypatch.setattr(chat_route, "prefetch_few_shot_example", boom_fewshot)
    monkeypatch.setattr(chat_route, "ProfileService", lambda store=None: object())
    monkeypatch.setattr(chat_route, "build_store", lambda s: None)
    from insightxpert_api.llm import gemini as gemini_mod
    class _FakeLLM:
        def __init__(self, **_kw): pass
    monkeypatch.setattr(gemini_mod, "GeminiLLM", _FakeLLM)

    body = SimpleNamespace(db_id="db1", message="q", agent_mode="auto")
    cu = SimpleNamespace(id="u1")
    settings = SimpleNamespace(
        gemini_api_key="x", gemini_chat_model="m", gemini_embed_model="e",
    )

    decision, profile, fewshot = await chat_route._preflight_concurrent(
        body, cu, settings, None, None
    )
    assert decision == "DECISION"
    assert profile == "PROFILE"
    assert fewshot is None  # swallowed
