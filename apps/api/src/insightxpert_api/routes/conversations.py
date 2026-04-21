"""Conversation CRUD routes.

Thin HTTP surface over ``ConversationStore``. All entries are scoped by
``session_id`` from the signed cookie; other sessions are invisible by construction.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth.dependencies import require_session
from ..auth.session import SessionClaims
from ..services.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
    get_conversation_store,
)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


class ConversationPatch(BaseModel):
    title: str | None = None
    starred: bool | None = None


@router.get("")
async def list_conversations(
    claims: SessionClaims = Depends(require_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> list[dict[str, Any]]:
    convos = store.list(claims.session_id)
    convos_sorted = sorted(convos, key=lambda c: c.updated_at, reverse=True)
    return [ConversationStore.to_dict(c) for c in convos_sorted]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    claims: SessionClaims = Depends(require_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> dict[str, Any]:
    try:
        convo = store.get(claims.session_id, conversation_id)
    except ConversationNotFoundError as e:
        raise HTTPException(status_code=404, detail="not_found") from e
    return ConversationStore.to_dict(convo)


@router.patch("/{conversation_id}")
async def patch_conversation(
    conversation_id: str,
    body: ConversationPatch,
    claims: SessionClaims = Depends(require_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> dict[str, Any]:
    try:
        if body.title is not None:
            store.rename(claims.session_id, conversation_id, body.title)
        if body.starred is not None:
            store.set_starred(claims.session_id, conversation_id, body.starred)
        convo = store.get(claims.session_id, conversation_id)
    except ConversationNotFoundError as e:
        raise HTTPException(status_code=404, detail="not_found") from e
    return ConversationStore.to_dict(convo)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    claims: SessionClaims = Depends(require_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> Response:
    try:
        store.delete(claims.session_id, conversation_id)
    except ConversationNotFoundError as e:
        raise HTTPException(status_code=404, detail="not_found") from e
    return Response(status_code=204)
