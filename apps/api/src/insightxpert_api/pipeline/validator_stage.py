"""SqlValidatorStage — parse the candidate SQL with sqlglot (sqlite dialect).

On failure the stage records the error on ``ctx.state["error"]`` so the downstream
Refiner can read it; on success the error slot is cleared. This design avoids
raising out of the stage (which would abort the pipeline) so refine loops work.
"""
from __future__ import annotations

import sqlglot

from ..sse.chunks import ChunkType, ErrorPayload, StatusPayload
from .stage import PipelineContext


class SqlValidatorStage:
    """Validate ``ctx.state["sql"]`` via ``sqlglot.parse_one``."""

    name = "sql_validator"

    async def run(self, ctx: PipelineContext, _: object) -> str | None:
        sql = ctx.state.get("sql", "")
        try:
            sqlglot.parse_one(sql, dialect="sqlite")
        except Exception as exc:  # sqlglot raises SqlglotError subclasses
            ctx.state["error"] = f"sql_validation_failed: {exc}"
            if ctx.emitter is not None:
                await ctx.emitter.emit(
                    ChunkType.ERROR,
                    ErrorPayload(code="sql_validation_failed", detail=str(exc)),
                )
            return None
        # Clear any stale error from a prior iteration.
        ctx.state.pop("error", None)
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.STATUS, StatusPayload(message="SQL valid"))
        return sql
