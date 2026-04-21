"""SqlExecutorStage — run ``ctx.state["sql"]`` through ``DatabaseConnector``.

Emits ``sql_executing`` before the query and ``rows_returned`` on success. On
any execution failure (syntax error not caught by the validator, timeout,
forbidden write) the error is set on ``ctx.state["error"]`` so the Refiner can
pick it up.
"""
from __future__ import annotations

from ..db.connector import DatabaseConnector
from ..services.database_service import DatabaseService
from ..sse.chunks import (
    ChunkType,
    ErrorPayload,
    RowsReturnedPayload,
    SQLExecutingPayload,
)
from .stage import PipelineContext


class SqlExecutorStage:
    """Execute the current SQL and cache results on ``ctx.state``."""

    name = "sql_executor"

    def __init__(self, db_svc: DatabaseService, row_limit: int = 1000) -> None:
        self._db = db_svc
        self._row_limit = row_limit

    async def run(self, ctx: PipelineContext, _: object) -> dict | None:
        # Skip if a prior stage already flagged an error and nothing refined it yet.
        if ctx.state.get("error"):
            return None
        sql = ctx.state.get("sql", "")
        db_id = ctx.state["db_id"]
        ref = self._db.resolve(ctx.session_id, db_id)
        if ref is None:
            ctx.state["error"] = f"database_not_found: {db_id}"
            return None

        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.SQL_EXECUTING, SQLExecutingPayload(sql=sql))

        try:
            result = DatabaseConnector(ref.local_path, row_limit=self._row_limit).execute(sql)
        except Exception as exc:
            ctx.state["error"] = f"sql_execution_failed: {exc}"
            if ctx.emitter is not None:
                await ctx.emitter.emit(
                    ChunkType.ERROR,
                    ErrorPayload(code="sql_execution_failed", detail=str(exc)),
                )
            return None

        payload = RowsReturnedPayload(
            columns=result.columns,
            row_count=len(result.rows),
            rows=result.rows,
            execution_time_ms=result.execution_time_ms,
        )
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.ROWS_RETURNED, payload)
        ctx.state["rows"] = {
            "columns": result.columns,
            "rows": result.rows,
            "execution_time_ms": result.execution_time_ms,
        }
        return ctx.state["rows"]
