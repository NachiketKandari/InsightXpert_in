"""Chat routes: SSE streaming (``/chat``), polled (``/chat/poll``), final-only (``/chat/answer``).

All three drive the same pipeline; they differ only in how chunks are surfaced to the caller.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
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
) -> tuple[PipelineContext, Any]:
    store = build_store(settings)
    db_svc = DatabaseService(bundled_dir=settings.bundled_dbs_dir, store=store)
    prof_svc = ProfileService(store)
    pipeline = default_pipeline(settings, db_svc, prof_svc)

    convo = convo_store.get_or_create(claims.session_id, body.conversation_id)
    convo_store.append_message(
        claims.session_id, convo.conversation_id, role="user", content=body.message
    )

    ctx = PipelineContext(
        session_id=claims.session_id,
        conversation_id=convo.conversation_id,
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
        answer = str(ctx.state.get("answer", "")) or (
            "Query returned "
            f"{len(ctx.state.get('rows', []))} rows."
        )
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
    emitter = EventEmitter(convo.conversation_id)
    ctx, pipeline = _build_pipeline_and_ctx(
        body=body, claims=claims, settings=settings, convo_store=convo_store, emitter=emitter
    )
    # Fire pipeline on a background task so EventSourceResponse can start streaming
    # the emitter's queue before the pipeline finishes.
    asyncio.create_task(_run_pipeline(pipeline, ctx, convo_store))
    return EventSourceResponse(emitter.stream())
