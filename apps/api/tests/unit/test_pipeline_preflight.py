"""Unit tests for ``pipeline.preflight`` and ProfilerStage prefetch hand-off.

These tests pin the behavioural contract:
  1. ``prefetch_profile`` runs the (sync) ``ProfileService.load`` call off the
     event loop so it can race against other awaits.
  2. When two preflight tasks each take ~100 ms, running them concurrently
     completes in ~100 ms — not ~200 ms — proving they actually run in
     parallel rather than sequentially.
  3. ``ProfilerStage`` consumes ``ctx.state["__prefetched_profile"]`` instead
     of re-loading from the cache, and still emits the standard
     ``profile_loaded`` chunk so the SSE timeline is unchanged.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from insightxpert_api.pipeline.preflight import prefetch_profile
from insightxpert_api.pipeline.profiler_stage import ProfilerStage
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import ChunkType
from insightxpert_api.sse.emitter import EventEmitter
from insightxpert_api.vendored.pipeline_core.models.profile import (
    DatabaseProfile,
    TableProfile,
)


class _SlowProfSvc:
    """Stand-in for ProfileService whose blocking ``load`` sleeps for ``delay``."""

    def __init__(self, delay: float, profile: DatabaseProfile | None) -> None:
        self.delay = delay
        self.profile = profile

    def load(self, session_id: str, db_id: str) -> DatabaseProfile | None:  # noqa: ARG002
        time.sleep(self.delay)
        return self.profile


class _FakeDbSvc:
    def resolve(self, session_id: str, db_id: str):  # noqa: ARG002
        class _Ref:
            local_path = "/nonexistent.sqlite"

        return _Ref()


def _make_profile(db_id: str = "demo") -> DatabaseProfile:
    return DatabaseProfile(
        db_id=db_id,
        tables=[TableProfile(name="t", columns=[], row_count=0)],
    )


@pytest.mark.asyncio
async def test_prefetch_profile_runs_off_event_loop() -> None:
    """A 100ms blocking ``load`` should not block other concurrent awaits."""
    profile = _make_profile()
    svc = _SlowProfSvc(delay=0.1, profile=profile)

    async def _other_work() -> str:
        await asyncio.sleep(0.1)
        return "done"

    start = time.perf_counter()
    profile_result, other = await asyncio.gather(
        prefetch_profile(svc, "s", "demo"),
        _other_work(),
    )
    elapsed = time.perf_counter() - start

    # Concurrency: max(0.1, 0.1) ≈ 0.1s (not 0.2s sequential). Allow 80ms
    # epsilon for test-runner jitter — that's still well under sequential.
    assert elapsed < 0.18, f"preflight ran sequentially: {elapsed:.3f}s"
    assert profile_result is profile
    assert other == "done"


@pytest.mark.asyncio
async def test_prefetch_profile_swallows_errors() -> None:
    """Preflight is best-effort — exceptions return ``None``, never raise."""

    class _BoomSvc:
        def load(self, session_id: str, db_id: str):  # noqa: ARG002
            raise RuntimeError("metadata DB unavailable")

    result = await prefetch_profile(_BoomSvc(), "s", "demo")
    assert result is None


@pytest.mark.asyncio
async def test_profiler_stage_consumes_prefetched_profile() -> None:
    """ProfilerStage skips ``prof_svc.load`` when a prefetched profile is present."""
    prefetched = _make_profile()

    class _NeverLoadProfSvc:
        loaded = False

        def load(self, session_id: str, db_id: str):  # noqa: ARG002
            type(self).loaded = True
            return None

    stage = ProfilerStage(db_svc=_FakeDbSvc(), prof_svc=_NeverLoadProfSvc())
    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["db_id"] = "demo"
    ctx.state["__prefetched_profile"] = prefetched

    result = await stage.run(ctx, None)

    assert result is prefetched
    assert ctx.state["profile"] is prefetched
    # Hand-off key is consumed (popped) so a re-run doesn't double-handle it.
    assert "__prefetched_profile" not in ctx.state
    assert _NeverLoadProfSvc.loaded is False


@pytest.mark.asyncio
async def test_profiler_stage_still_emits_profile_loaded_with_prefetch() -> None:
    """``profile_loaded`` chunk must still fire even when the profile came from preflight."""
    prefetched = _make_profile()

    class _StubProfSvc:
        def load(self, session_id: str, db_id: str):  # noqa: ARG002
            return None

    stage = ProfilerStage(db_svc=_FakeDbSvc(), prof_svc=_StubProfSvc())
    emitter = EventEmitter(conversation_id="c")
    ctx = PipelineContext(session_id="s", conversation_id="c", emitter=emitter)
    ctx.state["db_id"] = "demo"
    ctx.state["__prefetched_profile"] = prefetched

    await stage.run(ctx, None)
    await emitter.close()

    frames: list[str] = []
    async for frame in emitter.stream():
        frames.append(frame)
    joined = "".join(frames)
    assert ChunkType.PROFILE_LOADED.value in joined
    # Marked as cache-hit since it came from prefetch.
    assert '"from_cache": true' in joined


@pytest.mark.asyncio
async def test_concurrent_preflight_wall_time() -> None:
    """End-to-end: profile prefetch concurrent with a simulated LLM call.

    Mirrors the route-level pattern: ``classify_mode`` (LLM) racing against
    ``prefetch_profile`` (DB read). Sequential wall time would be ~0.2s; the
    concurrent path should land near ~0.1s.
    """
    profile = _make_profile()
    svc = _SlowProfSvc(delay=0.1, profile=profile)

    async def _fake_classifier() -> str:
        await asyncio.sleep(0.1)
        return "basic"

    start = time.perf_counter()
    profile_task = asyncio.create_task(prefetch_profile(svc, "s", "demo"))
    decision = await _fake_classifier()
    loaded = await profile_task
    elapsed = time.perf_counter() - start

    assert decision == "basic"
    assert loaded is profile
    assert elapsed < 0.18, f"preflight + classifier ran sequentially: {elapsed:.3f}s"
