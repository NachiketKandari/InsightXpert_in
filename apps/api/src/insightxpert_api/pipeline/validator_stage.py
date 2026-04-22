"""SqlValidatorStage — parse the candidate SQL with the correct sqlglot dialect.

Dialect is read from ``ctx.state["db_dialect"]``, which is written by
``ProfilerStage`` when it resolves the DatabaseRef.  Falls back to ``"sqlite"``
so the stage stays safe when run in isolation (e.g. unit tests without a full
pipeline context).

On failure the stage records the error on ``ctx.state["error"]`` so the downstream
Refiner can read it; on success the error slot is cleared. This design avoids
raising out of the stage (which would abort the pipeline) so refine loops work.
"""
from __future__ import annotations

import sqlglot

from ..db.dialects import get_adapter
from ..sse.chunks import ChunkType, ErrorPayload, StatusPayload
from .stage import PipelineContext


class SqlValidatorStage:
    """Validate ``ctx.state["sql"]`` via ``sqlglot.parse_one``."""

    name = "sql_validator"

    async def run(self, ctx: PipelineContext, _: object) -> str | None:
        sql = ctx.state.get("sql", "")
        # Resolve the sqlglot dialect from the adapter registered for this DB.
        # db_dialect is written by ProfilerStage; fall back to sqlite explicitly
        # (conscious fallback — not a silent default).
        raw_dialect: str = ctx.state.get("db_dialect", "sqlite")
        adapter = get_adapter(raw_dialect)
        sqlglot_dialect = adapter.sqlglot_dialect
        try:
            sqlglot.parse_one(sql, dialect=sqlglot_dialect)
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
