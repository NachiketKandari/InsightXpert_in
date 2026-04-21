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


def test_to_sse_produces_data_line_and_double_newline():
    c = ChatChunk(type=ChunkType.ANSWER_GENERATED, data=AnswerGeneratedPayload(text="ok"))
    frame = c.to_sse()
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame[len("data: ") : -len("\n\n")])
    assert payload["type"] == "answer_generated"


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
    assert "one" in collected[0]
    assert "two" in collected[1]
    assert collected[2] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_emitter_ignores_emit_after_close():
    em = EventEmitter(conversation_id="c1")
    await em.close()
    await em.emit(ChunkType.STATUS, StatusPayload(message="late"))  # should no-op
    # stream should yield only DONE
    frames = [f async for f in em.stream()]
    assert frames == ["data: [DONE]\n\n"]
