"""Unit tests for ``SchemaLinkerStage`` with a stubbed LLM."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from insightxpert_api.pipeline.linker_stage import SchemaLinkerStage
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter
from insightxpert_api.vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnStats,
    DatabaseProfile,
    TableProfile,
)

CLEAN_PROMPT = str(
    Path(__file__).resolve().parents[2]
    / "src/insightxpert_api/vendored/pipeline_core/prompts/single_prompt_linking_clean.j2"
)

CANDIDATE_BLOCK = (
    "Query 1:\n```sql\nSELECT id FROM users\n```\n"
    "Query 2:\n```sql\nSELECT name FROM users\n```\n"
    "Query 3:\n```sql\nSELECT id, name FROM users\n```\n"
    "Query 4:\n```sql\nSELECT COUNT(*) FROM users\n```\n"
    "Query 5:\n```sql\nSELECT id FROM users WHERE name = 'alice'\n```\n"
)


def _fake_profile() -> DatabaseProfile:
    stats = ColumnStats(count=3, null_count=0, distinct_count=3)
    return DatabaseProfile(
        db_id="demo",
        tables=[
            TableProfile(
                name="users",
                row_count=3,
                columns=[
                    ColumnProfile(name="id", type="INTEGER", stats=stats),
                    ColumnProfile(name="name", type="TEXT", stats=stats),
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_linker_emits_events_and_populates_state():
    llm = MagicMock()

    async def _gen(prompt: str, **_):
        return CANDIDATE_BLOCK

    llm.async_generate = _gen
    # No vector/LSH index → semantic + literals matches are empty but events still fire.

    stage = SchemaLinkerStage(llm=llm, prompt_path=CLEAN_PROMPT)

    emitter = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=emitter)
    ctx.state["question"] = "how many users?"
    ctx.state["db_id"] = "demo"
    ctx.state["profile"] = _fake_profile()

    result = await stage.run(ctx, None)
    await emitter.close()

    assert "schema_text" in result
    assert "column_sources" in result
    assert "users" in result["linked_tables"]
    assert ctx.state["schema_text"] == result["schema_text"]

    frames = []
    async for f in emitter.stream():
        frames.append(f)
    joined = "".join(frames)

    # Assert SSE events fired in order.
    expected_order = [
        ChunkType.SCHEMA_LINKING_STARTED.value,
        ChunkType.CANDIDATE_SQLS_GENERATED.value,
        ChunkType.LITERALS_EXTRACTED.value,
        ChunkType.SEMANTIC_MATCHES.value,
        ChunkType.JOIN_PATHS_ADDED.value,
        ChunkType.LINKED_SCHEMA_FINAL.value,
    ]
    positions = [joined.index(f'"type": "{ev}"') for ev in expected_order]
    assert positions == sorted(positions)
