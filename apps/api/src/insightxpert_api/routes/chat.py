"""Chat routes: SSE streaming (``/chat``), polled (``/chat/poll``), final-only (``/chat/answer``).

All three drive the same pipeline; they differ only in how chunks are surfaced to the caller.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..auth.dependencies import require_session
from ..auth.session import SessionClaims
from ..config import Settings, get_settings
from ..logging import get_logger
from ..pipeline import default_pipeline
from ..pipeline.stage import PipelineContext
from ..services.conversation_store import ConversationStore, get_conversation_store
from ..services.database_service import DatabaseService
from ..services.profile_service import ProfileService
from ..sse.chunks import AnswerGeneratedPayload, ChunkType, ErrorPayload
from ..sse.emitter import EventEmitter
from ..storage import build_store

router = APIRouter(prefix="/api/v1", tags=["chat"])
log = get_logger("chat")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4096)
    db_id: str = Field(min_length=1, max_length=128)
    conversation_id: str | None = None


class ChatAnswerResponse(BaseModel):
    conversation_id: str
    answer: str
    sql: list[str]


class ChatPollResponse(BaseModel):
    conversation_id: str
    chunks: list[dict[str, Any]]


def _build_pipeline_and_ctx(
    body: ChatRequest,
    claims: SessionClaims,
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
        claims.session_id, conversation_id, role="user", content=body.message
    )

    ctx = PipelineContext(
        session_id=claims.session_id,
        conversation_id=conversation_id,
        emitter=emitter,
    )
    ctx.state.update(db_id=body.db_id, question=body.message)
    return ctx, pipeline


async def _run_pipeline(
    pipeline: Any,
    ctx: PipelineContext,
    convo_store: ConversationStore,
) -> None:
    """Drive the pipeline, emit final events, persist the assistant message."""
    emitter = ctx.emitter
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
        if emitter is not None:
            await emitter.close()


@router.post("/chat")
async def chat_sse(
    body: ChatRequest,
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> EventSourceResponse:
    """Run the pipeline and stream SSE chunks as they happen."""
    convo = convo_store.get_or_create(claims.session_id, body.conversation_id)
    emitter = EventEmitter(
        convo.conversation_id,
        on_emit=lambda chunk: convo_store.append_chunk(
            claims.session_id, convo.conversation_id, chunk.model_dump(mode="json")
        ),
    )
    ctx, pipeline = _build_pipeline_and_ctx(
        body=body, claims=claims, settings=settings, convo_store=convo_store,
        emitter=emitter, conversation_id=convo.conversation_id,
    )
    # Fire pipeline on a background task so EventSourceResponse can start streaming
    # the emitter's queue before the pipeline finishes.
    asyncio.create_task(_run_pipeline(pipeline, ctx, convo_store))
    return EventSourceResponse(emitter.stream())


async def _collect_chunks(
    pipeline: Any,
    ctx: PipelineContext,
    convo_store: ConversationStore,
) -> list[Any]:
    """Run the pipeline to completion, draining the emitter into a list of ChatChunks."""
    emitter = ctx.emitter
    assert emitter is not None

    task = asyncio.create_task(_run_pipeline(pipeline, ctx, convo_store))
    collected: list[Any] = []
    # Drain the queue until the sentinel (None) is pushed by emitter.close().
    while True:
        event = await emitter._queue.get()  # noqa: SLF001 — internal drain is deliberate
        if event is None:
            break
        collected.append(event)
    await task
    return collected


@router.post("/chat/poll", response_model=ChatPollResponse)
async def chat_poll(
    body: ChatRequest,
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> ChatPollResponse:
    """Run pipeline to completion and return the full list of chunks (non-streaming)."""
    convo = convo_store.get_or_create(claims.session_id, body.conversation_id)
    emitter = EventEmitter(
        convo.conversation_id,
        on_emit=lambda chunk: convo_store.append_chunk(
            claims.session_id, convo.conversation_id, chunk.model_dump(mode="json")
        ),
    )
    ctx, pipeline = _build_pipeline_and_ctx(
        body=body, claims=claims, settings=settings, convo_store=convo_store,
        emitter=emitter, conversation_id=convo.conversation_id,
    )
    chunks = await _collect_chunks(pipeline, ctx, convo_store)
    return ChatPollResponse(
        conversation_id=convo.conversation_id,
        chunks=[c.model_dump(mode="json") for c in chunks],
    )


@router.post("/chat/answer", response_model=ChatAnswerResponse)
async def chat_answer(
    body: ChatRequest,
    claims: SessionClaims = Depends(require_session),
    settings: Settings = Depends(get_settings),
    convo_store: ConversationStore = Depends(get_conversation_store),
) -> ChatAnswerResponse:
    """Run pipeline to completion; return final answer text + generated SQL list."""
    convo = convo_store.get_or_create(claims.session_id, body.conversation_id)
    emitter = EventEmitter(
        convo.conversation_id,
        on_emit=lambda chunk: convo_store.append_chunk(
            claims.session_id, convo.conversation_id, chunk.model_dump(mode="json")
        ),
    )
    ctx, pipeline = _build_pipeline_and_ctx(
        body=body, claims=claims, settings=settings, convo_store=convo_store,
        emitter=emitter, conversation_id=convo.conversation_id,
    )
    chunks = await _collect_chunks(pipeline, ctx, convo_store)

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
    return ChatAnswerResponse(
        conversation_id=convo.conversation_id,
        answer=answer,
        sql=sqls,
    )
