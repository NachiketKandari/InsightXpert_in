"""Unit tests for ``SqlGeneratorStage`` with a stubbed LLM."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from insightxpert_api.pipeline.generator_stage import SqlGeneratorStage
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter

# SF15: pipeline now uses the production 163-line prompt at
# vendored/pipeline_core/prompts/sql_generation.j2 (the prompts_clean
# stub was deleted). Path renamed for clarity but still exported as
# CLEAN_PROMPT to avoid touching downstream test references.
CLEAN_PROMPT = str(
    Path(__file__).resolve().parents[2]
    / "src/insightxpert_api/vendored/pipeline_core/prompts/sql_generation.j2"
)


@pytest.mark.asyncio
async def test_generator_extracts_sql_and_emits_chunk():
    llm = MagicMock()

    async def _gen(prompt: str, **_):
        assert "== Question ==" in prompt
        return "Here you go:\n```sql\nSELECT COUNT(*) FROM users;\n```\n"

    llm.async_generate = _gen
    stage = SqlGeneratorStage(llm=llm, prompt_path=CLEAN_PROMPT)

    emitter = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=emitter)
    ctx.state["question"] = "how many users?"
    ctx.state["schema_text"] = 'Table: "users"'

    sql = await stage.run(ctx, None)
    await emitter.close()

    assert sql == "SELECT COUNT(*) FROM users"
    assert ctx.state["sql"] == sql

    frames = []
    async for f in emitter.stream():
        frames.append(f)
    joined = "".join(frames)
    assert ChunkType.SQL_GENERATED.value in joined
    assert '"iteration": 0' in joined


@pytest.mark.asyncio
async def test_generator_falls_back_to_raw_response():
    llm = MagicMock()

    async def _gen(prompt: str, **_):
        return "SELECT 1"

    llm.async_generate = _gen
    stage = SqlGeneratorStage(llm=llm, prompt_path=CLEAN_PROMPT)

    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["question"] = "q"
    ctx.state["schema_text"] = "s"
    sql = await stage.run(ctx, None)
    assert sql == "SELECT 1"
