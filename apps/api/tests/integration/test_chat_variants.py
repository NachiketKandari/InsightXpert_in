"""Integration tests for the non-streaming chat variants (/chat/poll, /chat/answer).

Both endpoints drive the same pipeline as /chat but surface chunks differently:
    * /chat/poll returns the full chunk list as JSON (for debugging / E2E harness).
    * /chat/answer returns only the final answer text + the generated SQL list.

The shared ``patched_pipeline`` fixture from tests/conftest.py swaps in a 2-stage fake
so these stay Gemini-free and fast.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from insightxpert_api.pipeline.pipeline import Pipeline
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType, ErrorPayload


# --- /chat/poll -----------------------------------------------------------------


def test_chat_poll_last_chunk_is_metrics(authed_client: TestClient, patched_pipeline):
    """Spec §5.4: a terminal metrics chunk should precede [DONE]. The poll
    endpoint doesn't include [DONE] in its list; the last chunk should be metrics.
    """
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    chunks = r.json()["chunks"]
    assert chunks, "expected at least one chunk"
    last = chunks[-1]
    assert last["type"] == "metrics"
    assert isinstance(last["data"]["latency_ms"], int)


def test_chat_poll_returns_chunks_list(authed_client: TestClient, patched_pipeline):
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "conversation_id" in body
    assert isinstance(body["chunks"], list) and body["chunks"]
    types = [c["type"] for c in body["chunks"]]
    assert "sql_generated" in types
    assert "answer_generated" in types


def test_chat_poll_requires_session(client: TestClient, patched_pipeline):
    r = client.post(
        "/api/v1/chat/poll",
        json={"message": "x", "db_id": "california_schools"},
    )
    assert r.status_code == 401


# --- /chat/answer ---------------------------------------------------------------


def test_chat_answer_returns_answer_and_sql(authed_client: TestClient, patched_pipeline):
    r = authed_client.post(
        "/api/v1/chat/answer",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "The answer is 1."
    assert body["sql"] == ["SELECT 1 AS n"]
    assert body["conversation_id"]


def test_chat_answer_requires_session(client: TestClient, patched_pipeline):
    r = client.post(
        "/api/v1/chat/answer",
        json={"message": "x", "db_id": "california_schools"},
    )
    assert r.status_code == 401


class _ExecutorDictStage:
    """Fake executor that writes rows in the real dict shape {columns, rows, exec_ms}
    and does NOT write ctx.state["answer"] — to exercise the fallback path.
    """

    name = "sql_executor"

    async def run(self, ctx: PipelineContext, _) -> None:
        ctx.state["rows"] = {
            "columns": ["n"],
            "rows": [[343]],
            "execution_time_ms": 5,
        }
        return None


def test_chat_poll_persists_user_and_assistant_messages(
    authed_client: TestClient, patched_pipeline
):
    """QA FLAG 4: duplicate conversation created → returned id was always empty.
    After the fix, the returned conversation should contain both the user message
    and the assistant response.
    """
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    cid = r.json()["conversation_id"]
    g = authed_client.get(f"/api/v1/conversations/{cid}")
    assert g.status_code == 200
    messages = g.json()["messages"]
    assert len(messages) == 2
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant"]


def test_chat_poll_persists_chunks(authed_client: TestClient, patched_pipeline):
    """QA FLAG 4 follow-up: chunks should be appended to the conversation's
    replay buffer so the UI can rehydrate on refresh.
    """
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    cid = r.json()["conversation_id"]
    g = authed_client.get(f"/api/v1/conversations/{cid}")
    assert g.status_code == 200
    assert len(g.json()["chunks"]) > 0


def test_single_conversation_per_chat_call(authed_client: TestClient, patched_pipeline):
    """QA FLAG 4: one /chat/poll with conversation_id=None used to create two
    conversations (one returned to the caller, one where messages were stored).
    Only one new conversation should exist after a single chat call.
    """
    before = authed_client.get("/api/v1/conversations").json()
    r = authed_client.post(
        "/api/v1/chat/poll",
        json={"message": "count rows", "db_id": "california_schools"},
    )
    assert r.status_code == 200
    after = authed_client.get("/api/v1/conversations").json()
    assert len(after) == len(before) + 1


def test_chat_poll_fallback_answer_uses_inner_row_count(authed_client: TestClient):
    """QA FLAG 3a: the fallback answer computed `len(ctx.state['rows'])` which
    (since rows is a dict {columns, rows, exec_ms}) was always 3. Confirm the
    fallback now inspects `rows['rows']` and reports the correct count.
    """

    def fake_factory(_s, _db, _pf, *, pipeline_mode: str = "linked"):
        return Pipeline([_ExecutorDictStage()])

    with patch(
        "insightxpert_api.routes.chat.default_pipeline", side_effect=fake_factory
    ):
        r = authed_client.post(
            "/api/v1/chat/answer",
            json={"message": "count rows", "db_id": "california_schools"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "Query returned 1 rows."


class _ErrorStage:
    """Stage that emits an ERROR chunk — simulates a pipeline failure path."""

    name = "error_stage"

    async def run(self, ctx: PipelineContext, _) -> None:
        if ctx.emitter is not None:
            await ctx.emitter.emit(
                ChunkType.ERROR,
                ErrorPayload(code="invalid_db", detail="database not found: x"),
            )
        return None


def test_chat_answer_surfaces_unknown_db_error(authed_client: TestClient):
    """QA FLAG 3b: /chat/answer used to swallow ERROR chunks, returning 200
    with answer="". Any ERROR chunk should now raise HTTPException(500).
    """

    def fake_factory(_s, _db, _pf, *, pipeline_mode: str = "linked"):
        return Pipeline([_ErrorStage()])

    with patch(
        "insightxpert_api.routes.chat.default_pipeline", side_effect=fake_factory
    ):
        r = authed_client.post(
            "/api/v1/chat/answer",
            json={"message": "x", "db_id": "nonexistent"},
        )
    assert r.status_code >= 400
    assert r.status_code == 500
