"""Unit tests for ``SqlValidatorStage``."""
from __future__ import annotations

import pytest

from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.pipeline.validator_stage import SqlValidatorStage
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter


@pytest.mark.asyncio
async def test_validator_passes_valid_sql():
    stage = SqlValidatorStage()
    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["sql"] = "SELECT 1"
    result = await stage.run(ctx, None)
    assert result == "SELECT 1"
    assert "error" not in ctx.state


@pytest.mark.asyncio
async def test_validator_flags_broken_sql():
    stage = SqlValidatorStage()
    emitter = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=emitter)
    ctx.state["sql"] = "SELEC FROM WHERE"  # clearly broken
    result = await stage.run(ctx, None)
    await emitter.close()
    assert result is None
    assert "error" in ctx.state
    assert ctx.state["error"].startswith("sql_validation_failed")

    frames = []
    async for f in emitter.stream():
        frames.append(f)
    assert f'"type": "{ChunkType.ERROR.value}"' in "".join(frames)


@pytest.mark.asyncio
async def test_validator_clears_stale_error_on_success():
    stage = SqlValidatorStage()
    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["sql"] = "SELECT 1"
    ctx.state["error"] = "stale"
    await stage.run(ctx, None)
    assert "error" not in ctx.state
