import asyncio
import json

import pytest

from insightxpert_api.sse.chunks import (
    AnswerGeneratedPayload,
    ChatChunk,
    ChunkType,
    JoinEdgePayload,
    LinkedSchemaFinalPayload,
    StatusPayload,
)
from insightxpert_api.sse.emitter import EventEmitter


def test_status_chunk_serializes_with_type_and_data():
    c = ChatChunk(type=ChunkType.STATUS, data=StatusPayload(message="hello"))
    d = c.model_dump(mode="json")
    assert d["type"] == "status"
    assert d["data"]["message"] == "hello"
    assert isinstance(d["timestamp"], float)


def test_to_json_returns_raw_payload():
    c = ChatChunk(type=ChunkType.ANSWER_GENERATED, data=AnswerGeneratedPayload(text="ok"))
    raw = c.to_json()
    # No SSE framing — EventSourceResponse adds `data:` and `\n\n`.
    assert not raw.startswith("data:")
    assert "\n" not in raw
    payload = json.loads(raw)
    assert payload["type"] == "answer_generated"
    assert payload["data"]["text"] == "ok"


def test_linked_schema_final_roundtrip_with_column_sources():
    payload = LinkedSchemaFinalPayload(
        schema_text="CREATE TABLE x(id int);",
        linked_tables=["x"],
        linked_columns=["x.id"],
        column_sources={"x.id": ["trial_sql", "semantic"]},
    )
    c = ChatChunk(type=ChunkType.LINKED_SCHEMA_FINAL, data=payload, conversation_id="c1")
    d = c.model_dump(mode="json")
    assert d["data"]["column_sources"] == {"x.id": ["trial_sql", "semantic"]}
    assert d["conversation_id"] == "c1"


def test_join_edge_serializes_with_from_alias():
    edge = JoinEdgePayload(**{"from": "a.id", "to": "b.a_id", "kind": "declared"})
    d = edge.model_dump(mode="json", by_alias=True)
    assert d["from"] == "a.id"
    assert d["to"] == "b.a_id"


@pytest.mark.asyncio
async def test_emitter_streams_chunks_then_done():
    em = EventEmitter(conversation_id="c1")

    async def produce() -> None:
        await em.emit(ChunkType.STATUS, StatusPayload(message="one"))
        await em.emit(ChunkType.STATUS, StatusPayload(message="two"))
        await em.close()

    produce_task = asyncio.create_task(produce())
    collected: list[str] = []
    async for frame in em.stream():
        collected.append(frame)
    await produce_task

    assert len(collected) == 3
    # First two should be raw JSON payloads (no `data:` prefix).
    for frame in collected[:2]:
        assert not frame.startswith("data:")
        parsed = json.loads(frame)
        assert parsed["type"] == "status"
    assert "one" in collected[0]
    assert "two" in collected[1]
    assert collected[2] == "[DONE]"


@pytest.mark.asyncio
async def test_emitter_ignores_emit_after_close():
    em = EventEmitter(conversation_id="c1")
    await em.close()
    await em.emit(ChunkType.STATUS, StatusPayload(message="late"))  # should no-op
    # stream should yield only the DONE sentinel
    frames = [f async for f in em.stream()]
    assert frames == ["[DONE]"]
