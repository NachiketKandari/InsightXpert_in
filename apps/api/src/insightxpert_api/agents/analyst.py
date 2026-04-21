"""Analyst agent — our Phase A pipeline wrapped as a vendored-agent-compatible async generator.

Design notes
------------

The vendored orchestrator (``agents_core.orchestrator.orchestrator_loop``) and
its helper ``AnalystCollector`` live in a world where every streamed ``ChatChunk``
uses the *flat vendored* shape defined in ``agents_core.api.models``:

    class ChatChunk(BaseModel):
        type: str
        data: dict | None
        content: str | None
        sql: str | None
        tool_name: str | None
        args: dict | None
        conversation_id: str
        timestamp: float

Our Phase A pipeline stages, in contrast, emit ``insightxpert_api.sse.chunks.ChatChunk``
(the strict four-tier envelope) through an ``EventEmitter`` queue. The envelope
is what the frontend consumes.

The adapter therefore:

1. Runs the existing ``default_pipeline`` (profiler → schema_linker →
   sql_generator → sql_validator → sql_executor → sql_refiner) with an in-memory
   emitter whose queue we drain as chunks arrive.
2. For every emitted envelope-shape chunk, re-emits it as a *vendored-shape*
   ``ChatChunk`` (preserving the Tier-3 type string and payload in ``data``) so
   ``AnalystCollector`` — which sniffs ``chunk.sql``, ``chunk.content``,
   ``chunk.data["tool"]`` — can capture what it needs.
3. Before SQL execution, emits a **synthetic** tier-2 pair:

       ChatChunk(type="sql",  sql=<sql>, data=None, ...)       # collector.sql
       ChatChunk(type="tool_call",
                 data={"tool": "run_sql",
                       "arguments": {"sql": <sql>},
                       "agent": "analyst"},
                 sql=<sql>, ...)                                # collector log

   After execution, emits the matching tool_result with ``data["result"]`` as a
   **JSON string** — ``AnalystCollector.process_chunk`` parses this JSON to
   populate ``analyst_rows`` (see ``agents_core/common.py``).
4. After the answer is synthesised, emits ``ChatChunk(type="answer",
   content=<answer>, ...)`` so the collector can set ``.answer`` — which gates
   orchestrator Phase-2 enrichment evaluation.
5. Fire-and-forget autosaves the ``(question, sql)`` pair to the RAG store.

Any keyword args from the vendored call-site that our adapter doesn't need
(``ddl_override``, ``documentation_override``, ``stats_context``, ``stats_groups``,
``clarification_enabled``, ``rag_retrieval``, ``allowed_tables``, ``dataset_id``,
``org_id``, ``column_count``, ``skip_clarification``, …) are swallowed by
``**_ignored``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from ..pipeline import default_pipeline
from ..pipeline.stage import PipelineContext
from ..sse.chunks import (
    ChatChunk as EnvelopeChatChunk,  # our strict envelope
)
from ..sse.chunks import ChunkType
from ..sse.emitter import EventEmitter
from ..vendored.agents_core.api.models import ChatChunk  # flat vendored shape

logger = logging.getLogger("insightxpert_api.agents.analyst")


def _answer_text(envelope_chunk: EnvelopeChatChunk) -> str:
    data = envelope_chunk.data
    if hasattr(data, "text"):
        return str(data.text)  # type: ignore[attr-defined]
    if isinstance(data, dict):
        return str(data.get("text", ""))
    return ""


def _sql_text(envelope_chunk: EnvelopeChatChunk) -> str:
    data = envelope_chunk.data
    if hasattr(data, "sql"):
        return str(data.sql)  # type: ignore[attr-defined]
    if isinstance(data, dict):
        return str(data.get("sql", ""))
    return ""


def _rows_payload(envelope_chunk: EnvelopeChatChunk) -> tuple[list[str], list[list[object]], int]:
    data = envelope_chunk.data
    if hasattr(data, "columns"):
        return (
            list(getattr(data, "columns", []) or []),
            list(getattr(data, "rows", []) or []),
            int(getattr(data, "execution_time_ms", 0) or 0),
        )
    if isinstance(data, dict):
        return (
            list(data.get("columns", []) or []),
            list(data.get("rows", []) or []),
            int(data.get("execution_time_ms", 0) or 0),
        )
    return ([], [], 0)


def _to_vendored(envelope_chunk: EnvelopeChatChunk) -> ChatChunk:
    """Translate one envelope-shape chunk into the flat vendored shape.

    The ``type`` string is preserved verbatim (Tier-3 values remain Tier-3 on
    the wire). ``data`` is flattened to a plain dict so downstream consumers
    that do ``chunk.data.get(...)`` work uniformly.
    """
    payload = envelope_chunk.data
    if hasattr(payload, "model_dump"):
        data_dict: dict | None = payload.model_dump(mode="json", by_alias=True)  # type: ignore[assignment]
    elif isinstance(payload, dict):
        data_dict = dict(payload)
    else:
        data_dict = None

    type_value = envelope_chunk.type.value if hasattr(envelope_chunk.type, "value") else str(envelope_chunk.type)
    return ChatChunk(
        type=type_value,
        data=data_dict,
        content=None,
        sql=None,
        tool_name=None,
        args=None,
        conversation_id=envelope_chunk.conversation_id or "",
        timestamp=envelope_chunk.timestamp,
    )


def _rows_as_dicts(columns: list[str], rows: list[list[object]]) -> list[dict]:
    """Convert positional rows to list-of-dicts, matching AnalystCollector's contract."""
    if not columns:
        return []
    return [dict(zip(columns, row, strict=False)) for row in rows]


async def analyst_loop(
    question: str,
    llm: Any,
    db: Any,
    rag: Any,
    config: Any,
    conversation_id: str | None = None,
    history: list[dict] | None = None,
    *,
    db_id: str | None = None,
    session_id: str | None = None,
    **_ignored: Any,
) -> AsyncGenerator[ChatChunk, None]:
    """Run the Phase A pipeline and yield vendored-shape ChatChunks.

    Required ``_ignored`` kwargs the vendored orchestrator actually passes:

    - ``ddl_override``, ``documentation_override``
    - ``stats_context``, ``stats_groups``
    - ``clarification_enabled``, ``rag_retrieval``
    - ``allowed_tables``, ``dataset_id``, ``org_id``, ``column_count``
    - ``skip_clarification``

    Currently none of these alter pipeline behaviour — the route layer
    pre-resolves dataset context via ``db_id``/``session_id``.
    """
    cid = conversation_id or ""
    started = time.time()

    # Resolve db_id / session_id. Callers (our route) should pass these
    # explicitly. The vendored orchestrator doesn't pass them, so fall back
    # to whatever lives on config/db if available — but route layer owns this.
    effective_db_id = db_id or _ignored.get("db_id") or getattr(config, "db_id", None)
    effective_session_id = (
        session_id
        or _ignored.get("session_id")
        or getattr(config, "session_id", None)
        or "analyst"
    )
    if not effective_db_id:
        # Fail fast with an error chunk — the orchestrator's AnalystCollector
        # will flip had_error and enrichment is skipped.
        yield ChatChunk(
            type="error",
            content="analyst: db_id not provided",
            data={"code": "analyst_missing_db_id"},
            conversation_id=cid,
            timestamp=time.time(),
        )
        return

    # Build pipeline + emitter. The emitter's on_emit must be a no-op here —
    # conversation persistence is the route's job (fire-and-forget per spec O13),
    # and this adapter is also called from enrichment sub-tasks where we MUST
    # NOT double-write to the convo store.
    #
    # The route layer may pre-inject ``db_svc``/``prof_svc`` via ``_ignored`` so
    # tests (and callers that want to swap services) don't have to touch the
    # storage factory. If they're absent we build them from ``config``.
    db_svc = _ignored.get("db_svc")
    prof_svc = _ignored.get("prof_svc")
    if db_svc is None or prof_svc is None:
        from ..services.database_service import DatabaseService
        from ..services.profile_service import ProfileService
        from ..storage import build_store

        store = build_store(config)
        if db_svc is None:
            db_svc = DatabaseService(bundled_dir=config.bundled_dbs_dir, store=store)
        if prof_svc is None:
            prof_svc = ProfileService(store)
    pipeline = default_pipeline(config, db_svc, prof_svc)

    emitter = EventEmitter(cid)
    ctx = PipelineContext(
        session_id=effective_session_id,
        conversation_id=cid,
        emitter=emitter,
    )
    ctx.state.update(db_id=effective_db_id, question=question)

    pipeline_task = asyncio.create_task(_drive_pipeline(pipeline, ctx, emitter))

    final_sql: str = ""
    final_columns: list[str] = []
    final_rows_positional: list[list[object]] = []
    synthetic_pair_emitted = False
    had_error = False

    try:
        while True:
            event = await emitter._queue.get()  # noqa: SLF001
            if event is None:
                break

            # Capture final SQL (re-emitted on each refinement iteration).
            if event.type == ChunkType.sql_generated:
                final_sql = _sql_text(event) or final_sql

            # Executor emits SQL_EXECUTING immediately before running the query.
            # That's our cue to inject the synthetic tier-2 pair (once; refiner
            # re-executes on failure, so only the FIRST execution boundary gets
            # the synthetic "sql"/"tool_call" pair — downstream re-execution is
            # a retry, not a new tool call).
            if event.type == ChunkType.sql_executing and not synthetic_pair_emitted:
                sql = _sql_text(event) or final_sql
                if sql:
                    final_sql = sql
                    # Synthetic "sql" chunk so AnalystCollector captures .sql
                    yield ChatChunk(
                        type="sql",
                        sql=sql,
                        data=None,
                        content=None,
                        conversation_id=cid,
                        timestamp=time.time(),
                    )
                    # Synthetic tool_call (run_sql) so the UI's tool-step log
                    # and the AnalystCollector/orchestrator see the canonical
                    # agent-style invocation.
                    yield ChatChunk(
                        type="tool_call",
                        data={
                            "tool": "run_sql",
                            "arguments": {"sql": sql},
                            "agent": "analyst",
                        },
                        sql=sql,
                        tool_name="run_sql",
                        args={"sql": sql},
                        conversation_id=cid,
                        timestamp=time.time(),
                    )
                    synthetic_pair_emitted = True

            # Re-emit the Tier-3 chunk in vendored shape.
            yield _to_vendored(event)

            if event.type == ChunkType.rows_returned:
                cols, rows, _ = _rows_payload(event)
                final_columns = cols
                final_rows_positional = rows
                # Emit synthetic tool_result AFTER the real rows_returned, using
                # the JSON-string shape AnalystCollector expects.
                result_json = json.dumps(
                    {
                        "columns": cols,
                        "rows": _rows_as_dicts(cols, rows),
                        "row_count": len(rows),
                    }
                )
                yield ChatChunk(
                    type="tool_result",
                    data={
                        "tool": "run_sql",
                        "result": result_json,
                        "agent": "analyst",
                    },
                    tool_name="run_sql",
                    conversation_id=cid,
                    timestamp=time.time(),
                )

            if event.type == ChunkType.error:
                had_error = True

        await pipeline_task
    except Exception as exc:  # noqa: BLE001 — surface as error chunk
        logger.exception("analyst_loop failed: %s", exc)
        had_error = True
        yield ChatChunk(
            type="error",
            content=f"analyst_loop_failed: {exc}",
            data={"code": "analyst_loop_failed"},
            conversation_id=cid,
            timestamp=time.time(),
        )

    # --- Answer synthesis ---------------------------------------------------
    # The route's existing _run_pipeline() synthesises a fallback answer when
    # ctx.state["answer"] is empty. Replicate that here so the analyst-loop
    # surface mirrors that behaviour without introducing a new LLM call path.
    answer_text = ""
    if not had_error:
        answer_text = str(ctx.state.get("answer") or "")
        if not answer_text:
            answer_text = f"Query returned {len(final_rows_positional)} rows."

        # Tier-3 answer_generated for FE renderers (envelope-compatible).
        yield ChatChunk(
            type="answer_generated",
            data={"text": answer_text},
            conversation_id=cid,
            timestamp=time.time(),
        )
        # Tier-2 answer so AnalystCollector captures .answer and gates Phase-2.
        yield ChatChunk(
            type="answer",
            content=answer_text,
            data=None,
            conversation_id=cid,
            timestamp=time.time(),
        )

    # --- RAG auto-save (the flywheel) --------------------------------------
    if rag is not None and final_sql and not had_error:
        try:
            add = getattr(rag, "add_qa_pair", None)
            if add is not None:
                result = add(question=question, sql=final_sql, sql_valid=True)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as exc:  # noqa: BLE001 — flywheel never breaks the turn
            logger.debug("RAG autosave failed (non-fatal): %s", exc)

    _ = time.time() - started  # duration tracking — emitted via orchestrator metrics


async def _drive_pipeline(pipeline: Any, ctx: PipelineContext, emitter: EventEmitter) -> None:
    """Run the pipeline to completion and close the emitter queue.

    Mirrors the shape of ``routes.chat._run_pipeline`` but without the persistence
    side-effects (the adapter is agnostic to persistence; the route layer owns it).
    """
    from ..sse.chunks import ChunkType, ErrorPayload

    try:
        await pipeline.run_scalar(ctx, None)
        # Stash a fallback answer on ctx for the adapter to pick up. The
        # adapter itself emits the answer_generated / answer chunks AFTER the
        # pipeline drains, so we don't double-emit here.
        rows_payload = ctx.state.get("rows") or {}
        inner_rows = (
            rows_payload.get("rows", []) if isinstance(rows_payload, dict) else rows_payload
        )
        if not ctx.state.get("answer"):
            ctx.state["answer"] = f"Query returned {len(inner_rows)} rows."
    except Exception as exc:  # noqa: BLE001
        await emitter.emit(
            ChunkType.ERROR,
            ErrorPayload(code="pipeline_failed", detail=str(exc)),
        )
    finally:
        await emitter.close()
