"""Integration test for the chat SSE endpoint. Pipeline stages are replaced with fakes
so the test stays fast and deterministic (no real Gemini calls)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.pipeline.pipeline import Pipeline
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType, SQLGeneratedPayload, StatusPayload


class _FakeGen:
    name = "sql_generator"

    async def run(self, ctx: PipelineContext, _: Any) -> str:
        sql = "SELECT 1 AS n"
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=sql))
        ctx.state["sql"] = sql
        return sql


class _FakeExec:
    name = "sql_executor"

    async def run(self, ctx: PipelineContext, _: Any) -> None:
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.STATUS, StatusPayload(message="executed"))
        ctx.state["rows"] = [[1]]
        ctx.state["answer"] = "The answer is 1."
        return None


@pytest.fixture
def patched_pipeline(monkeypatch):
    """Swap default_pipeline for a 2-stage fake so SSE plumbing is tested without Gemini."""

    def fake_factory(_s, _db, _pf):
        return Pipeline([_FakeGen(), _FakeExec()])

    with patch("insightxpert_api.routes.chat.default_pipeline", side_effect=fake_factory):
        yield


def test_chat_sse_streams_chunks_and_terminates(
    authed_client: TestClient, patched_pipeline
):
    with authed_client.stream(
        "POST",
        "/api/v1/chat",
        json={"message": "count rows", "db_id": "california_schools"},
    ) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes())
    text = body.decode()
    assert "data: [DONE]" in text
    assert '"type":"status"' in text or '"type": "status"' in text
    assert "sql_generated" in text
    assert "answer_generated" in text


def test_chat_requires_session(client: TestClient, patched_pipeline):
    r = client.post(
        "/api/v1/chat",
        json={"message": "x", "db_id": "california_schools"},
    )
    assert r.status_code == 401


def test_chat_rejects_empty_message(authed_client: TestClient, patched_pipeline):
    r = authed_client.post(
        "/api/v1/chat",
        json={"message": "", "db_id": "california_schools"},
    )
    assert r.status_code == 422
