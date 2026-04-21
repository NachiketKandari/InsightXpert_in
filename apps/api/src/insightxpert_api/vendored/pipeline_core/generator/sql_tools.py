"""Shared run_sql tool definition and handler factory.

Used by SelfCorrector (SQL generation) and diagnose.py (causal diagnosis)
so both features use identical tool semantics.
"""
from __future__ import annotations

import logging
from typing import Any

from insightxpert_api.vendored.pipeline_core.db import open_db
from insightxpert_api.vendored.pipeline_core.evaluation.executor import SQLExecutor
from insightxpert_api.vendored.pipeline_core.generator.sql_validator import SQLValidator

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 5

# Tool declaration consumed by GeminiLLM.generate_with_tools()
RUN_SQL_TOOL: dict[str, Any] = {
    "name": "run_sql",
    "description": (
        "Execute a SQL SELECT query against the SQLite database and return "
        "the first 5 result rows (with column names). Use this to verify "
        "your SQL produces sensible results for the question. If the results "
        "look wrong, try a different query."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "sql": {
                "type": "STRING",
                "description": "The SQL SELECT query to execute.",
            },
        },
        "required": ["sql"],
    },
}


def make_run_sql_handler(db_id: str, benchmark: str = "mini_dev"):
    """Return a tool_handler callable bound to a specific database.

    The returned function has signature (tool_name: str, tool_args: dict) -> str
    matching what GeminiLLM.generate_with_tools() expects.
    """
    executor = SQLExecutor()
    validator = SQLValidator()
    calls_made = 0

    def handle_run_sql(tool_name: str, tool_args: dict[str, Any]) -> str:
        nonlocal calls_made
        sql = tool_args.get("sql", "").strip()
        if not sql:
            return "Error: empty SQL query"

        calls_made += 1
        valid, reason = validator.validate(sql)
        if not valid:
            return f"Validation error: {reason}"

        try:
            with open_db(db_id, benchmark=benchmark) as db:
                result = executor.execute(db, sql)
        except Exception as exc:
            return f"Database error: {exc}"

        if result.error:
            return f"Execution error: {result.error}"

        rows = result.rows[:_MAX_PREVIEW_ROWS]
        total = len(result.rows)
        cols = result.columns

        if not rows:
            return "Query returned 0 rows."

        lines = []
        if cols:
            lines.append("Columns: " + " | ".join(cols))
        for i, row in enumerate(rows):
            lines.append(f"Row {i+1}: " + " | ".join(str(v) for v in row))
        if total > _MAX_PREVIEW_ROWS:
            lines.append(f"... ({total} total rows, showing first {_MAX_PREVIEW_ROWS})")
        else:
            lines.append(f"({total} total rows)")

        logger.debug("run_sql tool call #%d returned %d rows", calls_made, total)
        return "\n".join(lines)

    return handle_run_sql
