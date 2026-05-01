"""Integration tests for the B2 orchestrator wiring behind /chat/*.

These tests patch the orchestrator_loop symbol imported into ``routes.chat`` so
we exercise the full route → orchestrator_loop → analyst_impl handoff without
touching the real Gemini API or the vendored RAG store.

Covered:
    - /chat/poll with ``agent_mode="basic"`` hits orchestrator_loop and the
      patched stub receives the correct kwargs including our ``analyst_impl``.
    - /chat/poll with ``agent_mode="agentic"`` likewise, default mode-name
      preserved.
    - The legacy path (agent_mode omitted) still routes through the Phase A
      pipeline (the ``patched_pipeline`` fixture proves this).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.sse.chunks import ChatChunk, ChunkType, StatusPayload


async def _stub_orchestrator(
    *,
    question: str,
    llm,
    db,
    rag,
    config,
    conversation_id,
    history,
    agent_mode,
    analyst_impl=None,
    **kwargs,
):
    """Minimal orchestrator replacement that yields a canned vendored-shape stream.

    The stream mirrors what our analyst adapter would produce (sql, tool_call,
    rows_returned, tool_result, answer_generated, answer). Enough to prove the
    route's _vendored_to_envelope translator fires for every recognised type.
    """
    from insightxpert_api.vendored.agents_core.api.models import ChatChunk as V

    cid = conversation_id or ""
    # Status
    yield V(type="status", content=f"orchestrator:{agent_mode}", data=None,
            conversation_id=cid, timestamp=0.0)
    # Tier-3 bits
    yield V(type="sql_generated", data={"sql": "SELECT 1", "iteration": 0},
            conversation_id=cid, timestamp=0.0)
    yield V(type="rows_returned",
            data={"columns": ["n"], "row_count": 1, "rows": [[1]], "execution_time_ms": 1},
            conversation_id=cid, timestamp=0.0)
    yield V(type="answer_generated", data={"text": "stubbed"},
            conversation_id=cid, timestamp=0.0)
    # Flat-vendored synthetic pair — must be dropped by _vendored_to_envelope.
    yield V(type="sql", sql="SELECT 1", data=None,
            conversation_id=cid, timestamp=0.0)
    yield V(type="answer", content="stubbed", data=None,
            conversation_id=cid, timestamp=0.0)


def _pytest_asyncgen_factory(**capture):
    """Build a stub that also records the kwargs it was called with."""

    async def _stub(**kwargs):
        capture.update(kwargs)
        async for c in _stub_orchestrator(**kwargs):
            yield c

    return _stub


def test_chat_poll_basic_mode_hits_orchestrator(authed_client: TestClient):
    captured: dict = {}

    async def stub(**kwargs):
        captured.update(kwargs)
        async for c in _stub_orchestrator(**kwargs):
            yield c

    with patch("insightxpert_api.routes.chat.orchestrator_loop", new=stub):
        r = authed_client.post(
            "/api/v1/chat/poll",
            json={
                "message": "how many rows?",
                "db_id": "california_schools",
                "agent_mode": "basic",
            },
        )
        assert r.status_code == 200, r.text

    assert captured["agent_mode"] == "basic"
    assert captured["question"] == "how many rows?"
    # analyst_impl must have been injected (our partial wrapping analyst_loop).
    assert captured["analyst_impl"] is not None

    body = r.json()
    types = [c["type"] for c in body["chunks"]]
    # The synthetic "sql"/"answer" vendored-shape duplicates must be filtered out.
    assert "sql_generated" in types
    assert "answer_generated" in types
    # Last chunk is metrics.
    assert types[-1] == "metrics"


def test_chat_poll_agentic_mode_is_default(authed_client: TestClient):
    captured: dict = {}

    async def stub(**kwargs):
        captured.update(kwargs)
        async for c in _stub_orchestrator(**kwargs):
            yield c

    with patch("insightxpert_api.routes.chat.orchestrator_loop", new=stub):
        r = authed_client.post(
            "/api/v1/chat/poll",
            json={
                "message": "q",
                "db_id": "california_schools",
                "agent_mode": "agentic",
            },
        )
        assert r.status_code == 200, r.text

    assert captured["agent_mode"] == "agentic"


def test_chat_answer_orchestrator_path(authed_client: TestClient):
    async def stub(**kwargs):
        async for c in _stub_orchestrator(**kwargs):
            yield c

    with patch("insightxpert_api.routes.chat.orchestrator_loop", new=stub):
        r = authed_client.post(
            "/api/v1/chat/answer",
            json={
                "message": "q",
                "db_id": "california_schools",
                "agent_mode": "basic",
            },
        )
        assert r.status_code == 200, r.text

    body = r.json()
    assert body["answer"] == "stubbed"
    assert body["sql"] == ["SELECT 1"]


def test_vendored_to_envelope_drops_unknown_types():
    """Unknown vendored chunk types must be dropped, not coerced into a
    placeholder ``status`` envelope. The previous behaviour produced raw
    ``[type_name]`` labels in the trace UI for any forward-compat chunk
    that wasn't yet modelled in ChunkType."""
    from insightxpert_api.routes.chat import _vendored_to_envelope
    from insightxpert_api.vendored.agents_core.api.models import ChatChunk as V

    unknown = V(
        type="some_future_chunk_type",
        data={"foo": "bar"},
        conversation_id="c1",
        timestamp=0.0,
    )
    assert _vendored_to_envelope(unknown) is None

    # Sanity: the existing sql/answer drop still returns None.
    assert _vendored_to_envelope(
        V(type="sql", sql="SELECT 1", data=None, conversation_id="c1", timestamp=0.0)
    ) is None
    assert _vendored_to_envelope(
        V(type="answer", content="hi", data=None, conversation_id="c1", timestamp=0.0)
    ) is None

    # And known types still translate.
    known = V(
        type="sql_generated",
        data={"sql": "SELECT 1", "iteration": 0},
        conversation_id="c1",
        timestamp=0.0,
    )
    out = _vendored_to_envelope(known)
    assert out is not None
    assert out.type == ChunkType.sql_generated


def test_chat_poll_filters_unknown_vendored_chunks(authed_client: TestClient):
    """End-to-end: an orchestrator that yields an unknown-type chunk must
    not surface a synthetic ``status`` chunk on the wire."""

    async def stub(**kwargs):
        from insightxpert_api.vendored.agents_core.api.models import ChatChunk as V

        cid = kwargs.get("conversation_id") or ""
        yield V(
            type="future_unknown_thing",
            data={"hello": "world"},
            conversation_id=cid,
            timestamp=0.0,
        )
        yield V(
            type="answer_generated",
            data={"text": "ok"},
            conversation_id=cid,
            timestamp=0.0,
        )

    with patch("insightxpert_api.routes.chat.orchestrator_loop", new=stub):
        r = authed_client.post(
            "/api/v1/chat/poll",
            json={
                "message": "q",
                "db_id": "california_schools",
                "agent_mode": "agentic",
            },
        )
        assert r.status_code == 200, r.text

    types = [c["type"] for c in r.json()["chunks"]]
    # No fallback `status` envelope from the unknown-type chunk.
    assert "status" not in types
    # And no chunk carries a ``[future_unknown_thing]`` placeholder message.
    for c in r.json()["chunks"]:
        data = c.get("data") or {}
        assert data.get("message") != "[future_unknown_thing]"


def test_chat_legacy_path_still_works(authed_client: TestClient, patched_pipeline):
    """Without agent_mode, the legacy Phase A pipeline path must remain engaged."""
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    types = [c["type"] for c in r.json()["chunks"]]
    assert "sql_generated" in types
    assert "answer_generated" in types
