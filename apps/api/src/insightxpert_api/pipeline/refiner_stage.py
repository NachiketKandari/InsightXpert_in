"""SqlRefinerStage — retry a broken SQL up to ``max_iters`` times.

Only runs when an upstream stage left ``ctx.state["error"]`` set. Each
iteration: render the refine prompt, call the LLM, validate the new SQL, and
execute it. Emits ``sql_generated`` (iteration=N) for every refinement.
"""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Template

from ..db.connector import DatabaseConnector
from ..llm import LLMProvider
from ..services.database_service import DatabaseService
from ..sse.chunks import (
    ChunkType,
    RowsReturnedPayload,
    SQLExecutingPayload,
    SQLGeneratedPayload,
)
from .stage import PipelineContext

_FENCED_SQL = re.compile(r"```sql\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


class SqlRefinerStage:
    """Iteratively refine a failed SQL query using the ``refine_sql.j2`` template."""

    name = "sql_refiner"

    def __init__(
        self,
        llm: LLMProvider,
        max_iters: int,
        db_svc: DatabaseService,
        prompt_path: str | None = None,
    ) -> None:
        self._llm = llm
        self._max_iters = max_iters
        self._db = db_svc
        if prompt_path is None:
            raise ValueError("SqlRefinerStage requires prompt_path")
        self._tpl = Template(Path(prompt_path).read_text())

    async def run(self, ctx: PipelineContext, _: object) -> str | None:
        if not ctx.state.get("error"):
            return ctx.state.get("sql")

        db_id = ctx.state["db_id"]
        ref = self._db.resolve(ctx.session_id, db_id)
        if ref is None:
            return ctx.state.get("sql")

        for i in range(1, self._max_iters + 1):
            prior_sql = ctx.state.get("sql", "")
            err = ctx.state.get("error", "")
            prompt = self._tpl.render(
                schema_text=ctx.state.get("schema_text", ""),
                question=ctx.state.get("question", ""),
                evidence="",
                previous_sql=prior_sql,
                error=err,
                iteration=i,
                prior_attempts=[],
            )
            resp = await self._llm.async_generate(prompt)
            m = _FENCED_SQL.search(resp)
            new_sql = (m.group(1) if m else resp).strip().rstrip(";").strip()
            ctx.state["sql"] = new_sql
            if ctx.emitter is not None:
                await ctx.emitter.emit(
                    ChunkType.SQL_GENERATED,
                    SQLGeneratedPayload(sql=new_sql, iteration=i),
                )
            # Inline validate + execute
            try:
                import sqlglot
                sqlglot.parse_one(new_sql, dialect="sqlite")
            except Exception as exc:
                ctx.state["error"] = f"sql_validation_failed: {exc}"
                continue

            if ctx.emitter is not None:
                await ctx.emitter.emit(
                    ChunkType.SQL_EXECUTING, SQLExecutingPayload(sql=new_sql)
                )
            try:
                result = DatabaseConnector(ref.local_path).execute(new_sql)
            except Exception as exc:
                ctx.state["error"] = f"sql_execution_failed: {exc}"
                continue

            ctx.state.pop("error", None)
            ctx.state["rows"] = {
                "columns": result.columns,
                "rows": result.rows,
                "execution_time_ms": result.execution_time_ms,
            }
            if ctx.emitter is not None:
                await ctx.emitter.emit(
                    ChunkType.ROWS_RETURNED,
                    RowsReturnedPayload(
                        columns=result.columns,
                        row_count=len(result.rows),
                        rows=result.rows,
                        execution_time_ms=result.execution_time_ms,
                    ),
                )
            return new_sql
        return ctx.state.get("sql")
