"""Public share viewer — no auth. Lives in its own file so grep('Depends(get_current_user)')
in this module returns zero and that is verifiable.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Response

from ..shared_snapshots import repository as snap_repo
from ..shared_snapshots.dto import SharedSnapshotMessage, SharedSnapshotPublic


router = APIRouter(prefix="/api/v1/public", tags=["public_shares"])


def _ts(raw: int | None) -> int:
    """Convert epoch-seconds integer to milliseconds for JS. Zero/null -> now."""
    val = raw or 0
    return (val * 1000) if val > 0 else int(time.time() * 1000)


def _is_visible(row: dict, now: int) -> bool:
    if row["revoked_at"] is not None:
        return False
    if row["expires_at"] is not None and row["expires_at"] <= now:
        return False
    return True


@router.get("/shares/{token}", response_model=SharedSnapshotPublic)
def get_public_share(token: str, response: Response) -> SharedSnapshotPublic:
    row = snap_repo.get_by_token(token)
    now = int(time.time())
    if row is None or not _is_visible(row, now):
        raise HTTPException(status_code=404, detail="not found")

    snap_repo.increment_view(token)

    response.headers["Cache-Control"] = "private, max-age=0, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"

    import json as _json

    payload = _json.loads(row["payload_json"])
    msgs = payload.get("messages", [])
    for m in msgs:
        if "created_at" in m:
            m["created_at"] = _ts(m["created_at"])
    return SharedSnapshotPublic(
        title=payload.get("title"),
        dataset_name=payload.get("dataset_name"),
        messages=[SharedSnapshotMessage(**m) for m in msgs],
        created_at=_ts(row["created_at"]),
        expires_at=row["expires_at"],
    )
