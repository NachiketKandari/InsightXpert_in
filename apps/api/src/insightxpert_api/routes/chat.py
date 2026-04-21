"""Chat routes: SSE streaming (``/chat``), polled (``/chat/poll``), final-only (``/chat/answer``).

All three drive the same pipeline; they differ only in how chunks are surfaced to the caller.

When ``agent_mode`` is ``"basic"`` or ``"agentic"`` on the request body, chat dispatches
to the vendored ``orchestrator_loop`` (B2). Without it (or ``agent_mode=None``), the legacy
Phase A pipeline path runs — preserved for backward compatibility with existing tests.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..metrics.service import record_turn as _record_turn

from ..agents.analyst import analyst_loop as _our_analyst_loop
from ..auth.current_user import CurrentUser, get_current_user
from ..config import Settings, get_settings
from ..logging import get_logger
from ..pipeline import default_pipeline
from ..pipeline.stage import PipelineContext
from ..services.conversation_store import ConversationStore, get_conversation_store
from ..services.database_service import DatabaseService
from ..services.profile_service import ProfileService
from ..sse.chunks import (
    AnswerGeneratedPayload,
    ChatChunk as EnvelopeChatChunk,
    ChunkType,
    ErrorPayload,
    MetricsPayload,
)
from ..sse.emitter import EventEmitter
from ..storage import build_store
from ..vendored.agents_core.api.models import ChatChunk as VendoredChatChunk
from ..vendored.agents_core.orchestrator import orchestrator_loop

router = APIRouter(prefix="/api/v1", tags=["chat"])
log = get_logger("chat")


def _extract_metrics_from_chunks(chunks: list[Any]) -> dict[str, Any]:
    """Pull the bits we need for query_metrics out of a collected chunk list.

    Returns a dict with keys: final_sql, duration_ms, tokens_in, tokens_out.
    Any missing signal falls back to None. Last sql_generated wins.
    """
    final_sql: str | None = None
    duration_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    for chunk in chunks:
        data = chunk.data if isinstance(chunk.data, dict) else (
            chunk.data.model_dump(mode="json")
            if hasattr(chunk.data, "model_dump")
            else {}
        )
        t = chunk.type
        if t == ChunkType.SQL_GENERATED:
            sql_text = data.get("sql")
            if sql_text:
                final_sql = str(sql_text)
        elif t == ChunkType.METRICS:
            if duration_ms is None and data.get("latency_ms") is not None:
                duration_ms = int(data["latency_ms"])
            if data.get("prompt_tokens") is not None:
                tokens_in = int(data["prompt_tokens"])
            if data.get("output_tokens") is not None:
                tokens_out = int(data["output_tokens"])
    return {
        "final_sql": final_sql,
        "duration_ms": duration_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def _schedule_record_turn(
    background_tasks: BackgroundTasks,
    *,
    cu: CurrentUser,
    conversation_id: str,
    body: "ChatRequest",
    chunks: list[Any],
) -> None:
    extracted = _extract_metrics_from_chunks(chunks)
    background_tasks.add_task(
        _record_turn,
        user_id=cu.id,
        conversation_id=conversation_id,
        db_id=body.db_id,
        question=body.message,
        final_sql=extracted["final_sql"],
        agent_mode=body.agent_mode,
        tokens_in=extracted["tokens_in"],
        tokens_out=extracted["tokens_out"],
        duration_ms=extracted["duration_ms"],
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4096)
    db_id: str = Field(min_length=1, max_length=128)
    conversation_id: str | None = None
    # B2: when set, dispatch to the vendored orchestrator_loop with our
    # pipeline-wrapping analyst injected. When None, route falls back to the
    # legacy Phase A pipeline path so existing tests/clients stay green.
    agent_mode: Literal["basic", "agentic"] | None = None


class ChatAnswerResponse(BaseModel):
    conversation_id: str
    answer: str
    sql: list[str]


class ChatPollResponse(BaseModel):
    conversation_id: str
    chunks: list[dict[str, Any]]


def _build_pipeline_and_ctx(
    body: ChatRequest,
    cu: CurrentUser,
    settings: Settings,
    convo_store: ConversationStore,
    emitter: EventEmitter | None,
    conversation_id: str,
) -> tuple[PipelineContext, Any]:
    """Build a pipeline + context for an already-resolved conversation_id.

    Previously this helper called ``convo_store.get_or_create(body.conversation_id)``
    a second time after the route had already done so — when ``body.conversation_id``
    was None (the common first-turn case) the second call minted a different UUID,
    so the route returned convo A but messages accumulated in convo B (QA FLAG 4).
    The caller now owns ``get_or_create`` and passes the resolved id through.
    """
    store = build_store(settings)
    db_svc = DatabaseService(bundled_dir=settings.bundled_dbs_dir, store=store)
    prof_svc = ProfileService(store)
    pipeline = default_pipeline(settings, db_svc, prof_svc)

    convo_store.append_message(
        cu.id, conversation_id, role="user", content=body.message
    )

    ctx = PipelineContext(
        session_id=cu.id,
        conversation_id=conversation_id,
        emitter=emitter,
    )
    ctx.state.update(db_id=body.db_id, question=body.message)
    return ctx, pipeline


def _llm_token_totals(source: Any) -> tuple[int, int]:
    """Read accumulated Gemini usage tokens off an LLM-bearing object.

    Accepts either a ``GeminiLLM`` directly or a ``Pipeline`` that has
    ``.llm`` stashed on it by ``default_pipeline``. Returns ``(input, output)``,
    defaulting to ``(0, 0)`` when the source exposes no counters (keeps
    existing test doubles — e.g. the 2-stage fake in ``conftest.py`` — green).
    """
    llm = getattr(source, "llm", source)
    return (
        int(getattr(llm, "input_tokens_used", 0) or 0),
        int(getattr(llm, "output_tokens_used", 0) or 0),
    )


async def _run_pipeline(
    pipeline: Any,
    ctx: PipelineContext,
    convo_store: ConversationStore,
    model: str | None = None,
    metrics_record: dict[str, Any] | None = None,
) -> None:
    """Drive the pipeline, emit final events, persist the assistant message.

    When ``metrics_record`` is provided, a query_metrics row is written in the
    finally block (off-loop via asyncio.to_thread). The dict must contain
    ``user_id``, ``conversation_id``, ``db_id``, ``question``, ``agent_mode``.
    """
    emitter = ctx.emitter
    start = time.monotonic()
    try:
        await pipeline.run_scalar(ctx, None)
        # executor_stage stores `rows` as a dict {columns, rows, execution_time_ms}.
        # The previous fallback did `len(ctx.state['rows'])` which is always 3.
        # Until an answerer LLM stage lands (Slice 1), compute the correct row count.
        rows_payload = ctx.state.get("rows") or {}
        inner_rows = (
            rows_payload.get("rows", []) if isinstance(rows_payload, dict) else rows_payload
        )
        answer = str(ctx.state.get("answer", "")) or f"Query returned {len(inner_rows)} rows."
        if emitter is not None:
            await emitter.emit(
                ChunkType.ANSWER_GENERATED, AnswerGeneratedPayload(text=answer)
            )
        convo_store.append_message(
            ctx.session_id, ctx.conversation_id, role="assistant", content=answer
        )
    except Exception as exc:  # noqa: BLE001 — log + emit + fail the stream gracefully
        log.error(
            "chat.pipeline_failed",
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        if emitter is not None:
            await emitter.emit(
                ChunkType.ERROR,
                ErrorPayload(code="pipeline_failed", detail=str(exc)),
            )
    finally:
        # Emit a terminal metrics chunk (spec §5.4) before closing, carrying
        # the Gemini ``usage_metadata`` tokens accumulated by the per-turn
        # GeminiLLM (stashed on ``pipeline.llm`` by ``default_pipeline``).
        latency_ms = int((time.monotonic() - start) * 1000)
        tokens_in, tokens_out = _llm_token_totals(pipeline)
        total_tokens = (tokens_in + tokens_out) if (tokens_in or tokens_out) else None
        if emitter is not None:
            await emitter.emit(
                ChunkType.METRICS,
                MetricsPayload(
                    latency_ms=latency_ms,
                    prompt_tokens=tokens_in or None,
                    output_tokens=tokens_out or None,
                    total_tokens=total_tokens,
                    model=model,
                ),
            )
            await emitter.close()
        if metrics_record is not None:
            try:
                sql_state = ctx.state.get("sql")
                await asyncio.to_thread(
                    _record_turn,
                    user_id=metrics_record["user_id"],
                    conversation_id=metrics_record["conversation_id"],
                    db_id=metrics_record["db_id"],
                    question=metrics_record["question"],
                    final_sql=str(sql_state) if sql_state else None,
                    agent_mode=metrics_record.get("agent_mode"),
                    tokens_in=tokens_in or None,
                    tokens_out=tokens_out or None,
                    duration_ms=latency_ms,
                )
            except Exception:  # noqa: BLE001
                pass


@router.post("/chat")
async def chat_sse(
    body: ChatRequest,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> EventSourceResponse:
    """Run the pipeline and stream SSE chunks as they happen."""
    convo = convo_store.get_or_create(cu.id, body.conversation_id)
    emitter = EventEmitter(
        convo.conversation_id,
        on_emit=lambda chunk: convo_store.append_chunk(
            cu.id, convo.conversation_id, chunk.model_dump(mode="json")
        ),
    )
    if body.agent_mode is not None:
        asyncio.create_task(
            _run_orchestrator(
                body, cu, settings, convo_store, emitter, convo.conversation_id,
                record_metrics=True,
            )
        )
    else:
        ctx, pipeline = _build_pipeline_and_ctx(
            body=body, cu=cu, settings=settings, convo_store=convo_store,
            emitter=emitter, conversation_id=convo.conversation_id,
        )
        # Fire pipeline on a background task so EventSourceResponse can start streaming
        # the emitter's queue before the pipeline finishes.
        asyncio.create_task(
            _run_pipeline(
                pipeline, ctx, convo_store,
                model=settings.gemini_chat_model,
                metrics_record={
                    "user_id": cu.id,
                    "conversation_id": convo.conversation_id,
                    "db_id": body.db_id,
                    "question": body.message,
                    "agent_mode": body.agent_mode,
                },
            )
        )
    return EventSourceResponse(emitter.stream())


def _vendored_to_envelope(vendored: VendoredChatChunk) -> EnvelopeChatChunk | None:
    """Translate a flat vendored ChatChunk to our strict four-tier envelope.

    Returns ``None`` for chunks we intentionally drop — specifically the synthetic
    ``type="sql"`` (duplicate of sql_generated) and ``type="answer"`` (duplicate
    of answer_generated) emitted by our analyst adapter for AnalystCollector
    compatibility. Those are internal to the vendored orchestrator's bookkeeping
    and shouldn't surface on the wire.

    Unknown type strings fall through with ``data`` set to the vendored's ``data``
    dict — keeps forward-compat with orchestrator chunks we haven't modelled yet
    (orchestrator_plan, agent_trace, enrichment_trace, insight, clarification).
    """
    t = vendored.type
    # Drop internal-duplicate chunks.
    if t in ("sql", "answer"):
        return None

    # Try to map the type string to our ChunkType enum. If the string isn't a
    # known value, we still emit the chunk with the raw type (FE can treat it
    # as opaque) — but our Pydantic envelope requires a ChunkType value, so we
    # fall back to ``status`` with the original string preserved in data.
    try:
        ct = ChunkType(t)
    except ValueError:
        return EnvelopeChatChunk(
            type=ChunkType.status,
            data={"message": f"[{t}]", **(vendored.data or {})},
            conversation_id=vendored.conversation_id or None,
            timestamp=vendored.timestamp,
        )

    # For chunks the orchestrator emits with flat top-level fields, lift into data.
    data: dict = dict(vendored.data or {})
    if vendored.content is not None and "content" not in data:
        data.setdefault("content", vendored.content)
    if vendored.sql is not None and "sql" not in data:
        data.setdefault("sql", vendored.sql)
    if vendored.tool_name is not None and "tool" not in data:
        data.setdefault("tool", vendored.tool_name)

    return EnvelopeChatChunk(
        type=ct,
        data=data,
        conversation_id=vendored.conversation_id or None,
        timestamp=vendored.timestamp,
    )


async def _run_orchestrator(
    body: ChatRequest,
    cu: CurrentUser,
    settings: Settings,
    convo_store: ConversationStore,
    emitter: EventEmitter,
    conversation_id: str,
    record_metrics: bool = False,
) -> None:
    """Drive the vendored orchestrator_loop with our analyst injected, translate
    each yielded vendored chunk to our envelope, and push through the emitter.

    Persistence of the user turn happens once at entry (mirrors the legacy path).
    The emitter's ``on_emit`` hook handles chunk persistence. At the end we append
    the final assistant answer (drawn from the translated ``answer_generated``
    chunk if present) and a metrics chunk, then close the emitter.
    """
    from ..llm import GeminiLLM

    start = time.monotonic()

    convo_store.append_message(
        cu.id, conversation_id, role="user", content=body.message
    )

    # Build services once so our analyst re-uses them (no double build_store).
    store = build_store(settings)
    db_svc = DatabaseService(bundled_dir=settings.bundled_dbs_dir, store=store)
    prof_svc = ProfileService(store)

    llm = GeminiLLM(
        api_key=settings.gemini_api_key,
        model=settings.gemini_chat_model,
        embed_model=settings.gemini_embed_model,
    )

    # Our analyst is dispatched via the vendored orchestrator's analyst_impl
    # kwarg (see vendored_patches/0003-inject-analyst-impl.patch). Capture
    # route-level context (db_id, session_id, service DI) via functools.partial
    # so the orchestrator's call-site — which doesn't know about our shapes —
    # passes only the vendored-standard kwargs.
    from functools import partial

    analyst_impl = partial(
        _our_analyst_loop,
        db_id=body.db_id,
        session_id=cu.id,
        db_svc=db_svc,
        prof_svc=prof_svc,
    )

    answer_text = ""
    final_sql_seen: str | None = None
    try:
        async for vchunk in orchestrator_loop(
            question=body.message,
            llm=llm,
            db=None,
            rag=None,
            config=settings,
            conversation_id=conversation_id,
            history=[],
            agent_mode=body.agent_mode or "agentic",
            analyst_impl=analyst_impl,
            rag_retrieval=False,  # no vector store wired in v1
            stats_context_injection=False,  # StatsResolver not wired
            clarification_enabled=False,
        ):
            envelope = _vendored_to_envelope(vchunk)
            if envelope is None:
                continue
            # Remember the final answer for the assistant message persistence.
            if envelope.type == ChunkType.answer_generated:
                payload = envelope.data
                if isinstance(payload, dict):
                    answer_text = str(payload.get("text", "")) or answer_text
                elif hasattr(payload, "text"):
                    answer_text = str(payload.text) or answer_text  # type: ignore[attr-defined]
            elif envelope.type == ChunkType.sql_generated:
                sql_payload = envelope.data
                if isinstance(sql_payload, dict):
                    sql_val = sql_payload.get("sql")
                    if sql_val:
                        final_sql_seen = str(sql_val)
            # Push through the emitter (which persists chunks via on_emit).
            # Route directly — don't go through emit() which re-wraps.
            if emitter._on_emit is not None:  # noqa: SLF001 — mirrors emit()
                try:
                    emitter._on_emit(envelope)  # noqa: SLF001
                except Exception:  # noqa: BLE001
                    pass
            await emitter._queue.put(envelope)  # noqa: SLF001
        if not answer_text:
            answer_text = ""
        convo_store.append_message(
            cu.id, conversation_id, role="assistant", content=answer_text
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "chat.orchestrator_failed",
            session_id=cu.id,
            conversation_id=conversation_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        await emitter.emit(
            ChunkType.ERROR,
            ErrorPayload(code="orchestrator_failed", detail=str(exc)),
        )
    finally:
        latency_ms = int((time.monotonic() - start) * 1000)
        # Token totals are the sum of: (a) LLM calls the orchestrator made
        # directly via ``llm.chat`` (planner, evaluator, synthesiser,
        # quality-evaluator), plus (b) LLM calls our analyst adapter drove
        # through the pipeline via ``llm.async_generate``. Both paths feed
        # the same per-turn GeminiLLM instance, so one read on the adapter
        # yields the aggregate.
        tokens_in, tokens_out = _llm_token_totals(llm)
        total_tokens = (tokens_in + tokens_out) if (tokens_in or tokens_out) else None
        await emitter.emit(
            ChunkType.METRICS,
            MetricsPayload(
                latency_ms=latency_ms,
                prompt_tokens=tokens_in or None,
                output_tokens=tokens_out or None,
                total_tokens=total_tokens,
                model=settings.gemini_chat_model,
            ),
        )
        await emitter.close()
        if record_metrics:
            try:
                await asyncio.to_thread(
                    _record_turn,
                    user_id=cu.id,
                    conversation_id=conversation_id,
                    db_id=body.db_id,
                    question=body.message,
                    final_sql=final_sql_seen,
                    agent_mode=body.agent_mode,
                    tokens_in=tokens_in or None,
                    tokens_out=tokens_out or None,
                    duration_ms=latency_ms,
                )
            except Exception:  # noqa: BLE001
                pass


async def _collect_chunks(
    pipeline: Any,
    ctx: PipelineContext,
    convo_store: ConversationStore,
    model: str | None = None,
) -> list[Any]:
    """Run the pipeline to completion, draining the emitter into a list of ChatChunks."""
    emitter = ctx.emitter
    assert emitter is not None

    task = asyncio.create_task(_run_pipeline(pipeline, ctx, convo_store, model=model))
    collected: list[Any] = []
    # Drain the queue until the sentinel (None) is pushed by emitter.close().
    while True:
        event = await emitter._queue.get()  # noqa: SLF001 — internal drain is deliberate
        if event is None:
            break
        collected.append(event)
    await task
    return collected


async def _collect_chunks_orchestrator(
    body: ChatRequest,
    cu: CurrentUser,
    settings: Settings,
    convo_store: ConversationStore,
    emitter: EventEmitter,
    conversation_id: str,
) -> list[EnvelopeChatChunk]:
    """Run the orchestrator to completion and drain the emitter's queue."""
    task = asyncio.create_task(
        _run_orchestrator(body, cu, settings, convo_store, emitter, conversation_id)
    )
    collected: list[EnvelopeChatChunk] = []
    while True:
        event = await emitter._queue.get()  # noqa: SLF001
        if event is None:
            break
        collected.append(event)
    await task
    return collected


@router.post("/chat/poll", response_model=ChatPollResponse)
async def chat_poll(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> ChatPollResponse:
    """Run pipeline to completion and return the full list of chunks (non-streaming)."""
    convo = convo_store.get_or_create(cu.id, body.conversation_id)
    emitter = EventEmitter(
        convo.conversation_id,
        on_emit=lambda chunk: convo_store.append_chunk(
            cu.id, convo.conversation_id, chunk.model_dump(mode="json")
        ),
    )
    if body.agent_mode is not None:
        chunks = await _collect_chunks_orchestrator(
            body, cu, settings, convo_store, emitter, convo.conversation_id
        )
    else:
        ctx, pipeline = _build_pipeline_and_ctx(
            body=body, cu=cu, settings=settings, convo_store=convo_store,
            emitter=emitter, conversation_id=convo.conversation_id,
        )
        chunks = await _collect_chunks(pipeline, ctx, convo_store, model=settings.gemini_chat_model)
    _schedule_record_turn(
        background_tasks,
        cu=cu,
        conversation_id=convo.conversation_id,
        body=body,
        chunks=chunks,
    )
    return ChatPollResponse(
        conversation_id=convo.conversation_id,
        chunks=[c.model_dump(mode="json") for c in chunks],
    )


@router.post("/chat/answer", response_model=ChatAnswerResponse)
async def chat_answer(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    cu: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> ChatAnswerResponse:
    """Run pipeline to completion; return final answer text + generated SQL list."""
    convo = convo_store.get_or_create(cu.id, body.conversation_id)
    emitter = EventEmitter(
        convo.conversation_id,
        on_emit=lambda chunk: convo_store.append_chunk(
            cu.id, convo.conversation_id, chunk.model_dump(mode="json")
        ),
    )
    if body.agent_mode is not None:
        chunks = await _collect_chunks_orchestrator(
            body, cu, settings, convo_store, emitter, convo.conversation_id
        )
    else:
        ctx, pipeline = _build_pipeline_and_ctx(
            body=body, cu=cu, settings=settings, convo_store=convo_store,
            emitter=emitter, conversation_id=convo.conversation_id,
        )
        chunks = await _collect_chunks(pipeline, ctx, convo_store, model=settings.gemini_chat_model)

    answer = ""
    sqls: list[str] = []
    error_detail: str | None = None
    for chunk in chunks:
        # chunk.data may be a BaseModel or a dict; normalize to dict form.
        data = chunk.data if isinstance(chunk.data, dict) else chunk.data.model_dump(mode="json")
        if chunk.type == ChunkType.ANSWER_GENERATED:
            answer = str(data.get("text", ""))
        elif chunk.type == ChunkType.SQL_GENERATED:
            sql_text = data.get("sql")
            if sql_text:
                sqls.append(str(sql_text))
        elif chunk.type == ChunkType.ERROR:
            # Surface pipeline errors — /chat/answer used to swallow them and
            # return 200 with answer="" (QA FLAG 3b). /chat/poll intentionally
            # passes errors through, so we only raise here.
            error_detail = str(data.get("detail") or data.get("code") or "pipeline_error")
    if error_detail is not None:
        raise HTTPException(status_code=500, detail=error_detail)
    _schedule_record_turn(
        background_tasks,
        cu=cu,
        conversation_id=convo.conversation_id,
        body=body,
        chunks=chunks,
    )
    return ChatAnswerResponse(
        conversation_id=convo.conversation_id,
        answer=answer,
        sql=sqls,
    )
