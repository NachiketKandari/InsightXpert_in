"""B3 — Gemini ``usage_metadata`` tokens propagate through to the terminal
``metrics`` SSE chunk and land on ``query_metrics.tokens_in``/``tokens_out``.

Before this fix the metrics chunk was emitted without tokens and every
``query_metrics`` row had ``tokens_in=NULL``/``tokens_out=NULL`` even though
Gemini surfaces per-call usage in ``LLMResponse.input_tokens``/``output_tokens``.

Strategy: swap ``default_pipeline`` for a 2-stage fake whose ``Pipeline``
object carries a stub LLM with pre-set token counters. Exercises the real
route code path (``_run_pipeline`` emits metrics, ``_extract_metrics_from_chunks``
reads them, ``_record_turn`` writes the row).
"""

from __future__ import annotations

import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from insightxpert_api.pipeline.pipeline import Pipeline
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType, SQLGeneratedPayload


class _FakeGen:
    name = "sql_generator"

    async def run(self, ctx: PipelineContext, _):  # type: ignore[no-untyped-def]
        sql = "SELECT 1 AS n"
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=sql))
        ctx.state["sql"] = sql
        return sql


class _FakeExec:
    name = "sql_executor"

    async def run(self, ctx: PipelineContext, _):  # type: ignore[no-untyped-def]
        ctx.state["rows"] = {"columns": ["n"], "rows": [[1]], "execution_time_ms": 1}
        ctx.state["answer"] = "one."
        return None


class _FakeLLM:
    """Stands in for ``GeminiLLM`` — just carries the per-turn token counters
    the route layer reads when building the terminal metrics chunk."""

    input_tokens_used = 123
    output_tokens_used = 45


def _pipeline_with_tokens():
    p = Pipeline([_FakeGen(), _FakeExec()])
    p.llm = _FakeLLM()  # type: ignore[attr-defined]
    return p


def test_metrics_chunk_carries_gemini_tokens(authed_client: TestClient, fresh_db):
    """The terminal metrics chunk should carry prompt_tokens/output_tokens
    from the per-turn LLM's accumulator."""
    with patch(
        "insightxpert_api.routes.chat.default_pipeline",
        side_effect=lambda *_args, **_kw: _pipeline_with_tokens(),
    ):
        r = authed_client.post(
            "/api/v1/chat/poll",
            json={"message": "hello", "db_id": "california_schools"},
        )
    assert r.status_code == 200
    chunks = r.json()["chunks"]
    metrics = [c for c in chunks if c["type"] == "metrics"]
    assert len(metrics) == 1
    data = metrics[0]["data"]
    assert data["prompt_tokens"] == 123
    assert data["output_tokens"] == 45
    assert data["total_tokens"] == 168


def test_query_metrics_row_has_non_null_tokens(
    authed_client: TestClient, fresh_db
):
    """The background-task insert should land tokens_in/tokens_out (not NULL)."""
    with patch(
        "insightxpert_api.routes.chat.default_pipeline",
        side_effect=lambda *_args, **_kw: _pipeline_with_tokens(),
    ):
        r = authed_client.post(
            "/api/v1/chat/poll",
            json={"message": "token test", "db_id": "california_schools"},
        )
    assert r.status_code == 200
    convo_id = r.json()["conversation_id"]

    engine = create_engine(fresh_db)
    deadline = time.monotonic() + 3.0
    row = None
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tokens_in, tokens_out FROM query_metrics "
                    "WHERE conversation_id = :c"
                ),
                {"c": convo_id},
            ).fetchall()
        if rows:
            row = rows[0]
            break
        time.sleep(0.05)
    assert row is not None, "query_metrics row never landed"
    assert row.tokens_in == 123
    assert row.tokens_out == 45
