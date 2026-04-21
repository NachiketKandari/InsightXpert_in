"""Conversation CRUD routes.

Thin HTTP surface over ``ConversationStore``. All entries are scoped by
``session_id`` from the signed cookie; other sessions are invisible by construction.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth.current_user import CurrentUser, get_current_user
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
    cu: CurrentUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> list[dict[str, Any]]:
    convos = store.list(cu.id)
    convos_sorted = sorted(convos, key=lambda c: c.updated_at, reverse=True)
    return [ConversationStore.to_dict(c) for c in convos_sorted]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    cu: CurrentUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> dict[str, Any]:
    try:
        convo = store.get(cu.id, conversation_id)
    except ConversationNotFoundError as e:
        raise HTTPException(status_code=404, detail="not_found") from e
    return ConversationStore.to_dict(convo)


@router.patch("/{conversation_id}")
async def patch_conversation(
    conversation_id: str,
    body: ConversationPatch,
    cu: CurrentUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> dict[str, Any]:
    try:
        if body.title is not None:
            store.rename(cu.id, conversation_id, body.title)
        if body.starred is not None:
            store.set_starred(cu.id, conversation_id, body.starred)
        convo = store.get(cu.id, conversation_id)
    except ConversationNotFoundError as e:
        raise HTTPException(status_code=404, detail="not_found") from e
    return ConversationStore.to_dict(convo)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    cu: CurrentUser = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> Response:
    try:
        store.delete(cu.id, conversation_id)
    except ConversationNotFoundError as e:
        raise HTTPException(status_code=404, detail="not_found") from e
    return Response(status_code=204)
