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
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.pipeline.synthesizer_stage import AnswerSynthesizerStage
from insightxpert_api.sse.chunks import ChunkType


def _stream_from(chunks: list[str]):
    """Build a callable that returns an async iterator yielding the given chunks."""

    def factory(prompt: str) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for c in chunks:
                yield c

        return gen()

    return factory


def _stream_then_raise(chunks: list[str], exc: BaseException):
    """Yield ``chunks`` then raise ``exc`` from the stream iterator."""

    def factory(prompt: str) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for c in chunks:
                yield c
            raise exc

        return gen()

    return factory


class _RecordingEmitter:
    """Minimal emitter capturing (type, payload) tuples for test assertions."""

    def __init__(self) -> None:
        self.emitted: list[tuple[ChunkType, object]] = []

    async def emit(self, chunk_type: ChunkType, data: object) -> None:
        self.emitted.append((chunk_type, data))


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


def test_prompt_forbids_combined_footnote_markers() -> None:
    """The synthesizer prompt must explicitly forbid combined footnote markers
    like `[^3, 5, 6]` — markdown footnote parsers only understand single-id
    markers, so combined forms render as broken literal text in the UI.

    See answer-chunk.tsx + lib/footnote-parser.ts (expandCombinedFootnoteMarkers)
    for the FE defense-in-depth that catches whatever slips past the prompt.
    """
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "NEVER combine" in text, (
        "answer_synthesizer.j2 must explicitly forbid combined markers "
        "(text 'NEVER combine' missing). Multi-source claims must use "
        "adjacent markers like [^3][^5][^6], never [^3, 5, 6]."
    )
    # The negative examples and positive guidance must both appear.
    assert "[^3, 5, 6]" in text or "[^3,5,6]" in text
    assert "[^3][^5][^6]" in text


async def test_prompt_includes_references_section_and_rows_directive() -> None:
    """The synthesizer prompt must instruct the LLM to emit a 5th
    `## References` section using `{rows=...}` footnote directives, which the
    FE parses for clickable citations."""
    captured: dict[str, str] = {}

    def factory(prompt: str) -> AsyncIterator[str]:
        captured["prompt"] = prompt

        async def gen() -> AsyncIterator[str]:
            yield "**Direct Answer** ok."

        return gen()

    llm = MagicMock()
    llm.async_generate_stream = factory
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["customers", "table"]])

    await stage.run(ctx, None)

    prompt_arg = captured["prompt"]
    assert "## References" in prompt_arg
    assert "{rows=" in prompt_arg
    # Ensure the spec lists all four supported syntaxes.
    assert "{rows=N}" in prompt_arg
    assert "{rows=N,M,P}" in prompt_arg
    assert "{rows=N-M}" in prompt_arg


async def test_success_writes_answer_to_ctx_state() -> None:
    full_answer = (
        "**Direct Answer** This database has 5 tables.\n\n"
        "**Supporting Evidence** customers, gasstations, products, transactions_1k, yearmonth.\n\n"
        "**Data Provenance** All 5 rows from sqlite_master where type='table'.\n\n"
        "**Caveats** None."
    )
    llm = MagicMock()
    llm.async_generate_stream = _stream_from([full_answer])
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["customers", "table"], ["gasstations", "table"]])

    out = await stage.run(ctx, None)

    assert "Direct Answer" in ctx.state["answer"]
    assert "5 tables" in ctx.state["answer"]
    assert out == ctx.state["answer"]


async def test_llm_failure_falls_back_to_template() -> None:
    def boom(prompt: str):
        async def gen():
            raise RuntimeError("boom")
            yield ""  # pragma: no cover - unreachable, makes this an async gen

        return gen()

    llm = MagicMock()
    llm.async_generate_stream = boom
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["customers", "table"], ["gasstations", "table"]])

    out = await stage.run(ctx, None)

    assert ctx.state["answer"] == "Query returned 2 rows."
    assert out == "Query returned 2 rows."


async def test_empty_llm_response_falls_back_to_template() -> None:
    llm = MagicMock()
    llm.async_generate_stream = _stream_from([])
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["x", "y"]])

    await stage.run(ctx, None)

    assert ctx.state["answer"] == "Query returned 1 rows."


async def test_empty_rows_still_produces_answer() -> None:
    llm = MagicMock()
    llm.async_generate_stream = _stream_from(["**Direct Answer** No rows matched.\n"])
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([])

    await stage.run(ctx, None)

    assert "No rows matched" in ctx.state["answer"]


async def test_skips_when_upstream_error_set() -> None:
    llm = AsyncMock()
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["x", "y"]])
    ctx.state["error"] = "sql_execution_failed: table does not exist"

    await stage.run(ctx, None)

    # Stream method must not have been touched.
    assert not getattr(llm, "async_generate_stream", AsyncMock()).called
    assert "answer" not in ctx.state


async def test_streaming_emits_deltas_and_concatenates_state() -> None:
    """Happy path: 3 stream chunks produce 3 answer_delta emits + concatenated state."""
    llm = MagicMock()
    llm.async_generate_stream = _stream_from(
        ["**Direct ", "Answer** All ", "good."]
    )
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["customers", "table"]])
    emitter = _RecordingEmitter()
    ctx.emitter = emitter  # type: ignore[assignment]

    out = await stage.run(ctx, None)

    deltas = [(t, p) for (t, p) in emitter.emitted if t == ChunkType.answer_delta]
    assert len(deltas) == 3
    assert [p.text for (_, p) in deltas] == [
        "**Direct ",
        "Answer** All ",
        "good.",
    ]
    assert ctx.state["answer"] == "**Direct Answer** All good."
    assert out == ctx.state["answer"]


async def test_streaming_failure_mid_stream_falls_back() -> None:
    """If the stream raises after some chunks, fall back to the row-count template."""
    llm = MagicMock()
    llm.async_generate_stream = _stream_then_raise(
        ["**Direct Answer** partial"], RuntimeError("network blip")
    )
    stage = AnswerSynthesizerStage(llm=llm, prompt_path=str(PROMPT_PATH))
    ctx = _ctx_with_rows([["customers", "table"], ["gasstations", "table"]])
    emitter = _RecordingEmitter()
    ctx.emitter = emitter  # type: ignore[assignment]

    out = await stage.run(ctx, None)

    # The first chunk did get emitted before the failure.
    deltas = [(t, p) for (t, p) in emitter.emitted if t == ChunkType.answer_delta]
    assert len(deltas) == 1
    # State is the canonical fallback contract.
    assert ctx.state["answer"] == "Query returned 2 rows."
    assert out == "Query returned 2 rows."
