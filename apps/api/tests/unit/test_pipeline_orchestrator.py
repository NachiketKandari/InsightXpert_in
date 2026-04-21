import pytest

from insightxpert_api.pipeline.pipeline import Pipeline
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter


class _Upper:
    name = "upper"

    async def run(self, ctx, x):
        return x.upper()


class _Reverse:
    name = "reverse"

    async def run(self, ctx, x):
        return x[::-1]


class _Boom:
    name = "boom"

    async def run(self, ctx, x):
        raise RuntimeError("nope")


@pytest.mark.asyncio
async def test_pipeline_runs_stages_in_order():
    p = Pipeline([_Upper(), _Reverse()])
    ctx = PipelineContext(session_id="s", conversation_id="c")
    out = await p.run_scalar(ctx, "abc")
    assert out == "CBA"


@pytest.mark.asyncio
async def test_pipeline_rejects_empty_stage_list():
    with pytest.raises(ValueError):
        Pipeline([])


@pytest.mark.asyncio
async def test_pipeline_emits_status_per_stage_when_emitter_attached():
    em = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=em)
    p = Pipeline([_Upper(), _Reverse()])

    await p.run_scalar(ctx, "abc")
    await em.close()

    frames = [f async for f in em.stream()]
    # EventEmitter now yields raw JSON + the literal "[DONE]" sentinel — the
    # SSE framing is added by EventSourceResponse, not by the emitter.
    assert frames[-1] == "[DONE]"
    status_frames = [f for f in frames if '"type": "status"' in f or '"type":"status"' in f]
    assert len(status_frames) == 2  # one per stage


@pytest.mark.asyncio
async def test_pipeline_emits_error_chunk_and_reraises():
    em = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=em)
    p = Pipeline([_Upper(), _Boom()])

    with pytest.raises(RuntimeError):
        await p.run_scalar(ctx, "abc")
    await em.close()

    frames = [f async for f in em.stream()]
    error_frames = [f for f in frames if '"type": "error"' in f or '"type":"error"' in f]
    assert len(error_frames) == 1
    assert "boom_failed" in error_frames[0]


@pytest.mark.asyncio
async def test_pipeline_works_without_emitter():
    p = Pipeline([_Upper()])
    ctx = PipelineContext(session_id="s", conversation_id="c")
    assert await p.run_scalar(ctx, "hi") == "HI"
