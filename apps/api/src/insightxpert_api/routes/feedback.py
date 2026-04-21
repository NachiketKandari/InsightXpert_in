"""Feedback route.

v1 just structured-logs feedback so it shows up in Cloud Logging. Slice 2 will
persist to the conversation store; the contract is stable.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.current_user import CurrentUser, get_current_user
from ..logging import get_logger
from ..metrics.service import update_thumbs

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])
log = get_logger("feedback")


class FeedbackRequest(BaseModel):
    conversation_id: str
    message_id: str
    feedback: bool | None = None  # True=thumbs up, False=thumbs down, None=cleared
    comment: str | None = None


@router.post("")
async def post_feedback(
    body: FeedbackRequest,
    cu: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    log.info(
        "feedback.received",
        user_id=cu.id,
        conversation_id=body.conversation_id,
        message_id=body.message_id,
        feedback=body.feedback,
        has_comment=body.comment is not None,
    )
    # Map the bool feedback field to the 'up'/'down'/None shape that
    # query_metrics.thumbs expects, then update the most-recent metrics row
    # for the conversation. Off-loop so we never block the caller.
    if body.feedback is True:
        thumbs: str | None = "up"
    elif body.feedback is False:
        thumbs = "down"
    else:
        thumbs = None
    try:
        await asyncio.to_thread(update_thumbs, body.conversation_id, thumbs)
    except Exception:  # noqa: BLE001 — best-effort; feedback must never 500
        log.error("feedback.update_thumbs_failed", conversation_id=body.conversation_id)
    return {"status": "ok"}
