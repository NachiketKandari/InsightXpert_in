"""AnswerSynthesizerStage — turn executed SQL + result rows into a natural-language answer.

This is the final stage of the v1 text-to-SQL pipeline. It runs after
SqlRefinerStage and before the route's terminal answer_generated emit.

Design rationale (full notes in docs/architecture/answer-synthesis.md and
docs/superpowers/specs/2026-05-01-chat-answer-synthesis-and-render-fixes-design.md):

* Writes ctx.state["answer"] only — does NOT emit answer_generated itself.
  The route at routes/chat.py:_run_pipeline already reads ctx.state["answer"]
  and emits the chunk. Keeping that single emission point avoids the
  Phase-A double-emit pattern that produced the duplicate-table bug.
* Does not emit a metrics chunk. Token totals are aggregated by the route's
  terminal metrics emit via pipeline.llm.input_tokens_used / .output_tokens_used
  on the shared GeminiLLM instance.
* On any LLM failure, falls back to the existing "Query returned N rows."
  template — the same string the route used as a default before this stage
  existed. Failures are logged but never re-raised; an unsynthesized answer
  is preferable to an aborted turn.
* Skips entirely when ctx.state["error"] is set. The refiner is the last
  recovery point; if it could not produce rows, the route's error path
  surfaces the failure and we have nothing to summarize.

Inputs (from ctx.state, written by upstream stages):
  - question      : str            — the user's NL question
  - sql           : str            — the executed SQL
  - rows          : dict | None    — {"columns": list[str], "rows": list[list],
                                       "execution_time_ms": int} as written by
                                      SqlExecutorStage; may be missing if no
                                      rows came back (extremely rare).
  - schema_text   : str            — schema render produced by linker / full-schema
  - error         : str | None     — set by upstream on validator/executor failure

Effects:
  - Writes ctx.state["answer"] : str  — synthesized markdown OR fallback template

Returns:
  - The same string written to ctx.state["answer"], for symmetry with
    sibling stages whose return value feeds the next stage's input slot.
    Returns "" when the stage was skipped due to an upstream error.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Template

from ..llm import LLMProvider
from ..logging import get_logger
from ..sse.chunks import AnswerDeltaPayload, ChunkType
from .stage import PipelineContext

log = get_logger("pipeline.synthesizer_stage")


class AnswerSynthesizerStage:
    """Final stage: render answer_synthesizer.j2, call the LLM, write ctx.state['answer']."""

    name = "answer_synthesizer"

    def __init__(self, llm: LLMProvider, prompt_path: str) -> None:
        self._llm = llm
        self._tpl = Template(Path(prompt_path).read_text())

    async def run(self, ctx: PipelineContext, _: object) -> str:
        # If an upstream stage left an unrecovered error, do not synthesize —
        # the route's error path will surface it.
        if ctx.state.get("error"):
            return ""

        rows_payload = ctx.state.get("rows") or {}
        if isinstance(rows_payload, dict):
            columns = list(rows_payload.get("columns") or [])
            rows = list(rows_payload.get("rows") or [])
        else:
            # Tolerant: some upstream paths might pass rows directly.
            columns = []
            rows = list(rows_payload)
        row_count = len(rows)

        # DECISION(D-023): Answer synthesis emits [^N] footnote citations with
        # definitions — standard remark-gfm rendering, click-to-highlight FE
        # integration. Prompt templates instruct the LLM to use this format.
        prompt = self._tpl.render(
            question=ctx.state.get("question", ""),
            ddl=ctx.state.get("schema_text", ""),
            sql=ctx.state.get("sql", ""),
            columns=columns,
            rows=rows,
            row_count=row_count,
        )

        # Streaming path: yield deltas as they arrive so the FE can render the
        # answer materializing live. We accumulate locally and write the full
        # text to ctx.state["answer"] on completion — the route epilogue still
        # emits the terminal answer_generated chunk with the canonical text.
        #
        # Note: this stage emits incremental answer_delta chunks DURING run(),
        # which is a deliberate departure from the project's "stage writes
        # state, route emits" pattern. Streaming inherently requires
        # mid-execution emits; the pattern still holds for the terminal
        # answer_generated emission, which remains the route's responsibility.
        chunks: list[str] = []
        try:
            stream = self._llm.async_generate_stream(prompt)
            async with asyncio.timeout(60.0):
                async for delta in stream:
                    if not delta:
                        continue
                    chunks.append(delta)
                    if ctx.emitter is not None:
                        await ctx.emitter.emit(
                            ChunkType.answer_delta,
                            AnswerDeltaPayload(text=delta),
                        )
            answer = "".join(chunks).strip()
            if not answer:
                # Empty stream — treat as failure for fallback purposes.
                raise ValueError("empty response from LLM")
        except Exception as exc:  # noqa: BLE001 — never abort the turn on synthesis failure
            log.warning(
                "answer_synthesis_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                partial_chunks=len(chunks),
            )
            answer = f"Query returned {row_count} rows."

        ctx.state["answer"] = answer
        return answer
