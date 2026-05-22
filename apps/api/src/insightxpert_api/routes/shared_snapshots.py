"""Owner-scoped share routes. Auth required.

The public viewer lives in ``routes/public_shares.py`` — keep them in
separate files so the no-auth posture stays auditable by grep.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..auth.current_user import CurrentUser, get_current_user
from ..shared_snapshots import repository as snap_repo
from ..shared_snapshots import service as snap_service
from ..shared_snapshots.dto import SharedSnapshotMeta


router = APIRouter(prefix="/api/v1", tags=["shared_snapshots"])


class ShareCreateBody(BaseModel):
    acknowledge_uploaded: bool = False


def _ts(raw: int | None) -> int:
    """Convert epoch-seconds integer to milliseconds for JS. Zero/null -> now."""
    val = raw or 0
    return (val * 1000) if val > 0 else int(time.time() * 1000)


def _row_to_meta(row: dict) -> SharedSnapshotMeta:
    return SharedSnapshotMeta(
        token=row["token"],
        share_url=f"/share/{row['token']}",
        created_at=_ts(row["created_at"]),
        expires_at=row["expires_at"],
        revoked=row["revoked_at"] is not None,
        view_count=row["view_count"],
    )


@router.post(
    "/conversations/{conversation_id}/share",
    response_model=SharedSnapshotMeta,
)
def create_share(
    conversation_id: str,
    body: ShareCreateBody | None = None,
    cu: CurrentUser = Depends(get_current_user),
) -> SharedSnapshotMeta:
    body = body or ShareCreateBody()
    try:
        return snap_service.create_snapshot(
            conversation_id=conversation_id,
            user_id=cu.id,
            acknowledge_uploaded=body.acknowledge_uploaded,
        )
    except snap_service.ConversationNotFound:
        raise HTTPException(status_code=404, detail="conversation not found")
    except snap_service.NotConversationOwner:
        raise HTTPException(status_code=404, detail="conversation not found")
    except snap_service.SharingDisabled:
        raise HTTPException(
            status_code=403,
            detail="sharing has been disabled for this account",
        )
    except snap_service.UploadedShareRequiresConsent:
        raise HTTPException(
            status_code=409,
            detail="acknowledge_uploaded must be true to share an uploaded SQLite",
        )
    except snap_service.PostgresShareRefused:
        raise HTTPException(
            status_code=403,
            detail="sharing chats bound to live database connections (postgres/libsql) is refused in v1",
        )


@router.get(
    "/conversations/{conversation_id}/share",
    response_model=SharedSnapshotMeta,
)
def get_share(
    conversation_id: str,
    cu: CurrentUser = Depends(get_current_user),
) -> SharedSnapshotMeta:
    row = snap_repo.get_by_conversation(conversation_id, cu.id)
    if row is None:
        raise HTTPException(status_code=404, detail="not shared")
    return _row_to_meta(row)


@router.delete(
    "/conversations/{conversation_id}/share",
    status_code=204,
    response_class=Response,
)
def delete_share(
    conversation_id: str,
    cu: CurrentUser = Depends(get_current_user),
) -> Response:
    row = snap_repo.get_by_conversation(conversation_id, cu.id)
    if row is not None:
        snap_repo.revoke(row["token"])
    return Response(status_code=204)
