"""Verify SqlValidatorStage reads dialect from ctx.state["db_dialect"].

ILIKE is silently transpiled by sqlglot in sqlite mode (not a parse error).
We use the postgres-only regex match operator (``~``) which is a genuine
sqlglot ParseError on the sqlite dialect but valid on postgres.
"""
from __future__ import annotations

import pytest

from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.pipeline.validator_stage import SqlValidatorStage

# Postgres regex-match operator: raises ParseError when parsed as sqlite.
_REGEX_SQL = "SELECT x FROM t WHERE x ~ 'pattern'"


def _ctx(sql: str, dialect: str) -> PipelineContext:
    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["sql"] = sql
    ctx.state["db_dialect"] = dialect
    return ctx


@pytest.mark.asyncio
async def test_postgres_regex_operator_parses_on_postgres():
    """The ~ operator is valid postgres syntax — validator should pass."""
    stage = SqlValidatorStage()
    ctx = _ctx(_REGEX_SQL, dialect="postgres")
    result = await stage.run(ctx, None)
    assert result == _REGEX_SQL
    assert "error" not in ctx.state


@pytest.mark.asyncio
async def test_postgres_regex_operator_fails_on_sqlite():
    """The ~ operator is unknown to sqlite sqlglot — validator should record error."""
    stage = SqlValidatorStage()
    ctx = _ctx(_REGEX_SQL, dialect="sqlite")
    await stage.run(ctx, None)
    assert "sql_validation_failed" in ctx.state.get("error", "")


@pytest.mark.asyncio
async def test_missing_dialect_falls_back_to_sqlite():
    """When db_dialect is absent the stage should behave as sqlite (SELECT 1 passes)."""
    stage = SqlValidatorStage()
    ctx = PipelineContext(session_id="s", conversation_id="c")
    ctx.state["sql"] = "SELECT 1"
    # No db_dialect key — must not raise.
    result = await stage.run(ctx, None)
    assert result == "SELECT 1"
    assert "error" not in ctx.state
