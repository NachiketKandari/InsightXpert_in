"""Self-correcting SQL generator using LLM tool calling.

The LLM receives a `run_sql` tool it can invoke to execute SQL against
the actual database, inspect the results, and iterate until satisfied.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from insightxpert_api.vendored.pipeline_core.db import open_db
from insightxpert_api.vendored.pipeline_core.evaluation.executor import SQLExecutor
from insightxpert_api.vendored.pipeline_core.generator.sql_validator import SQLValidator
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.query import CandidateSQL

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)

# Tool definition for run_sql
_RUN_SQL_TOOL = {
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

_MAX_PREVIEW_ROWS = 5


class SelfCorrector:
    """Wraps SQL generation with an execution-feedback tool-calling loop."""

    def __init__(
        self,
        llm: BaseLLM,
        db_id: str,
        benchmark: str = "bird_dev",
        max_turns: int = 3,
    ) -> None:
        self._llm = llm
        self._db_id = db_id
        self._benchmark = benchmark
        self._max_turns = max_turns
        self._executor = SQLExecutor()
        self._validator = SQLValidator()
        self._calls_made = 0

    def _handle_run_sql(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        """Execute SQL and return a formatted preview of results."""
        sql = tool_args.get("sql", "").strip()
        if not sql:
            return "Error: empty SQL query"

        self._calls_made += 1

        # Validate first
        valid, reason = self._validator.validate(sql)
        if not valid:
            return f"Validation error: {reason}"

        try:
            with open_db(self._db_id, benchmark=self._benchmark) as db:
                result = self._executor.execute(db, sql)
        except Exception as exc:
            return f"Database error: {exc}"

        if result.error:
            return f"Execution error: {result.error}"

        # Format preview
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

        return "\n".join(lines)

    def generate(self, prompt: str) -> CandidateSQL:
        """Generate SQL with self-correction via tool calling.

        The prompt should be the fully rendered sql_generation.j2 template.
        We append instructions telling the LLM about the run_sql tool,
        then let it iterate.
        """
        self._calls_made = 0

        # Augment prompt with self-correction instructions
        augmented = prompt.rstrip()
        # Remove the trailing ```sql if present (we want the model to use the tool)
        if augmented.endswith("```sql"):
            augmented = augmented[:-6].rstrip()

        augmented += "\n\n" + _SELF_CORRECT_SUFFIX

        raw = self._llm.generate_with_tools(
            prompt=augmented,
            tools=[_RUN_SQL_TOOL],
            tool_handler=self._handle_run_sql,
            max_turns=self._max_turns,
        )

        sql = self._extract_sql(raw)
        logger.info(
            "SelfCorrector: produced SQL after %d tool call(s)", self._calls_made
        )
        return CandidateSQL(sql=sql, prompt=prompt)

    @staticmethod
    def _extract_sql(raw: str) -> str:
        """Extract SQL from fenced code block or raw text."""
        match = _FENCE_RE.search(raw)
        if match:
            sql = match.group(1).strip()
        else:
            sql = raw.strip()
        sql = sql.rstrip(";").strip()
        if ";" in sql:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt.upper().startswith("SELECT"):
                    return stmt
        return sql


_SELF_CORRECT_SUFFIX = """\
You have access to a `run_sql` tool that executes SQL against the actual database.

WORKFLOW:
1. Write your best SQL query and call `run_sql` to test it.
2. Check the results: Do the columns match what the question asks? Do the values make sense? Is the row count reasonable?
3. If anything looks wrong, revise your SQL and call `run_sql` again.
4. Once you are satisfied, output your final SQL in a ```sql``` code block.

IMPORTANT: You MUST call `run_sql` at least once before giving your final answer. After verifying, return ONLY the final ```sql``` block."""
