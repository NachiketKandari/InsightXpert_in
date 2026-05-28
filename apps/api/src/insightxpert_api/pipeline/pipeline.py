"""Sequential pipeline orchestrator. Stages run in declared order; output feeds next."""

from __future__ import annotations

import time
from typing import Any

from ..logging import get_logger
from ..sse.chunks import ChunkType, ErrorPayload, StatusPayload
from .stage import PipelineContext, Stage

log = get_logger("pipeline")


class Pipeline:
    """Composes an ordered list of stages. v1 is linear; branching lives in future slices."""

    def __init__(self, stages: list[Stage]) -> None:
        if not stages:
            raise ValueError("Pipeline requires at least one stage")
        self._stages = stages

    async def run_scalar(self, ctx: PipelineContext, seed: Any) -> Any:
        """Run stages sequentially, passing each stage's output as the next stage's input.

        Emits a ``status`` SSE chunk at each stage boundary and logs structured timing.
        On any stage exception: emits an ``error`` chunk (if an emitter is attached) and
        re-raises. The caller is responsible for closing the emitter in a ``finally``.
        """
        current = seed
        for stage in self._stages:
            start = time.perf_counter()
            log.info("stage.start", stage=stage.name, session_id=ctx.session_id,
                     conversation_id=ctx.conversation_id)
            if ctx.emitter is not None:
                await ctx.emitter.emit(
                    ChunkType.STATUS, StatusPayload(message=f"{stage.name}…")
                )
            try:
                current = await stage.run(ctx, current)
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                log.error(
                    "stage.error",
                    stage=stage.name,
                    ms=elapsed_ms,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                if ctx.emitter is not None:
                    await ctx.emitter.emit(
                        ChunkType.ERROR,
                        ErrorPayload(code=f"{stage.name}_failed", detail=str(exc)),
                    )
                raise
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            log.info("stage.end", stage=stage.name, ms=elapsed_ms)
        return current
