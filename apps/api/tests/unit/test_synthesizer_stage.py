"""Unit tests for AnswerSynthesizerStage.

The stage's contract:
  - Reads ctx.state["question"], ctx.state["sql"], ctx.state["rows"]
    (a dict with columns/rows/execution_time_ms keys, as written by
    SqlExecutorStage), ctx.state["schema_text"] (or full DDL).
  - Calls the LLM with the answer_synthesizer.j2 prompt.
  - On success: writes ctx.state["answer"] = response (str).
  - On failure: writes ctx.state["answer"] = "Query returned N rows."
    so the route's existing answer_generated emission has a fallback.
  - Never raises (failures are absorbed and logged).
  - When ctx.state["error"] is set, skips synthesis (the turn already
    failed; the route emits an error chunk).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.pipeline.synthesizer_stage import AnswerSynthesizerStage


PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "insightxpert_api"
    / "prompts"
    / "answer_synthesizer.j2"
)


def _ctx_with_rows(rows: list[list[object]]) -> PipelineContext:
    ctx = PipelineContext(session_id="s1", conversation_id="c1")
    ctx.state["question"] = "List the tables in this database."
    ctx.state["sql"] = "SELECT name, type FROM sqlite_master"
    ctx.state["schema_text"] = "CREATE TABLE customers (id INT);"
    ctx.state["rows"] = {
        "columns": ["name", "type"],
        "rows": rows,
        "execution_time_ms": 10,
    }
    return ctx


async def test_success_writes_answer_to_ctx_state() -> None:
    llm = AsyncMock()
    llm.async_generate = AsyncMock(
        return_value=(
            "**Direct Answer** This database has 5 tables.\n\n"
            "**Supporting Evidence** customers, gasstations, products, transactions_1k, yearmonth.\n\n"
            "**Data Provenance** All 5 rows from sqlite_master where type='table'.\n\n"
            "**Caveats** None."
        )
    )
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["customers", "table"], ["gasstations", "table"]])

    out = await stage.run(ctx, None)

    assert "Direct Answer" in ctx.state["answer"]
    assert "5 tables" in ctx.state["answer"]
    assert llm.async_generate.await_count == 1
    prompt_arg = llm.async_generate.await_args.args[0]
    assert "customers | table" in prompt_arg
    assert "List the tables in this database." in prompt_arg
    assert out == ctx.state["answer"]


async def test_llm_failure_falls_back_to_template() -> None:
    llm = AsyncMock()
    llm.async_generate = AsyncMock(side_effect=RuntimeError("boom"))
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["customers", "table"], ["gasstations", "table"]])

    out = await stage.run(ctx, None)

    assert ctx.state["answer"] == "Query returned 2 rows."
    assert out == "Query returned 2 rows."


async def test_empty_llm_response_falls_back_to_template() -> None:
    llm = AsyncMock()
    llm.async_generate = AsyncMock(return_value="")
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["x", "y"]])

    await stage.run(ctx, None)

    assert ctx.state["answer"] == "Query returned 1 rows."


async def test_empty_rows_still_produces_answer() -> None:
    llm = AsyncMock()
    llm.async_generate = AsyncMock(return_value="**Direct Answer** No rows matched.\n")
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([])

    await stage.run(ctx, None)

    assert "No rows matched" in ctx.state["answer"]


async def test_skips_when_upstream_error_set() -> None:
    llm = AsyncMock()
    llm.async_generate = AsyncMock()
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["x", "y"]])
    ctx.state["error"] = "sql_execution_failed: table does not exist"

    await stage.run(ctx, None)

    assert llm.async_generate.await_count == 0
    assert "answer" not in ctx.state
