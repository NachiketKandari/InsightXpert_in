"""Service layer: build and persist a ``SharedSnapshot``.

This is the *only* place that decides whether a share is allowed. Routes
must call into here — never write to ``shared_snapshots`` directly. Every
gating rule from the share-feature plan lives below.
"""

from __future__ import annotations

import secrets
import time

from sqlalchemy import select

from ..users.table import users
from ..databases import repository as db_repo
from ..db.engine import get_engine
from ..orchestration.table import conversations, messages
from . import repository as snap_repo
from .dto import SharedSnapshotMessage, SharedSnapshotMeta, SharedSnapshotPayload


# 90 days, in seconds. Default expiry on every snapshot.
_DEFAULT_TTL_SECONDS = 90 * 86400

_DISALLOWED_KINDS = {"postgres", "libsql", "sqlite_external"}


class ShareError(Exception):
    """Base class for share-create failures."""


class ConversationNotFound(ShareError):
    pass


class NotConversationOwner(ShareError):
    pass


class SharingDisabled(ShareError):
    """User-level admin flag has disabled sharing."""


class PostgresShareRefused(ShareError):
    """Sharing chats bound to non-bundled / non-uploaded DBs is disabled."""


class UploadedShareRequiresConsent(ShareError):
    """Uploaded SQLite needs an explicit ``acknowledge_uploaded=True``."""


def _classify_db(db_id: str | None, owner_user_id: str) -> str:
    """Return one of ``"none"``, ``"bundled"``, ``"uploaded"``, ``"refused"``.

    Bundled = no row in ``databases`` (filesystem-only) OR
              ``kind="sqlite_file"`` with ``owner_user_id IS NULL``.
    Uploaded = ``kind="sqlite_file"`` and ``owner_user_id == user``.
    Refused = ``kind`` in ``_DISALLOWED_KINDS`` (postgres / libsql / sqlite_external).
    """
    if db_id is None:
        return "none"
    row = db_repo.get(db_id)
    if row is None:
        return "bundled"
    kind = row.get("kind") or "sqlite_file"
    row_owner = row.get("owner_user_id")
    if kind in _DISALLOWED_KINDS:
        return "refused"
    if kind == "sqlite_file":
        if row_owner is None:
            return "bundled"
        if row_owner == owner_user_id:
            return "uploaded"
    # Unknown kind or sqlite_file owned by someone else — refuse by default.
    return "refused"


def _user_sharing_disabled(user_id: str) -> bool:
    with get_engine().connect() as conn:
        row = conn.execute(
            select(users.c.sharing_disabled).where(users.c.id == user_id)
        ).first()
    if row is None:
        return False
    return bool(row[0])


def _load_conversation(conversation_id: str, user_id: str) -> dict:
    for attempt in range(5):
        with get_engine().connect() as conn:
            crow = conn.execute(
                select(conversations).where(conversations.c.id == conversation_id)
            ).mappings().first()
            if crow is not None:
                if crow["user_id"] != user_id:
                    raise NotConversationOwner(conversation_id)
                mrows = conn.execute(
                    select(messages)
                    .where(messages.c.conversation_id == conversation_id)
                    .order_by(messages.c.created_at.asc())
                ).mappings().all()
                return {"conversation": dict(crow), "messages": [dict(m) for m in mrows]}
        if attempt < 4:
            time.sleep(0.1)
    raise ConversationNotFound(conversation_id)



def _build_payload(
    conv: dict,
    msg_rows: list[dict],
    dataset_name: str | None,
) -> SharedSnapshotPayload:
    msgs = [
        SharedSnapshotMessage(
            role=row["role"] if row["role"] in ("user", "assistant") else "assistant",
            content=row["content"],
            created_at=row["created_at"],
        )
        for row in msg_rows
        if row["role"] in ("user", "assistant")
    ]
    return SharedSnapshotPayload(
        title=conv.get("title"),
        dataset_name=dataset_name,
        messages=msgs,
    )


def _share_url(token: str) -> str:
    """Caller-friendly path. Frontend prepends origin."""
    return f"/share/{token}"


def create_snapshot(
    *,
    conversation_id: str,
    user_id: str,
    acknowledge_uploaded: bool,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> SharedSnapshotMeta:
    """Create a new snapshot. Raises a ``ShareError`` subclass on refusal."""

    if _user_sharing_disabled(user_id):
        raise SharingDisabled(user_id)

    bundle = _load_conversation(conversation_id, user_id)
    conv = bundle["conversation"]
    msg_rows = bundle["messages"]

    classification = _classify_db(conv.get("db_id"), user_id)
    if classification == "refused":
        raise PostgresShareRefused(conv.get("db_id"))
    if classification == "uploaded" and not acknowledge_uploaded:
        raise UploadedShareRequiresConsent(conv.get("db_id"))

    payload = _build_payload(
        conv=conv,
        msg_rows=msg_rows,
        dataset_name=conv.get("db_id") if classification != "none" else None,
    )

    token = secrets.token_urlsafe(24)
    now = int(time.time())
    expires = now + ttl_seconds if ttl_seconds > 0 else None

    snap_repo.insert(
        token=token,
        conversation_id=conversation_id,
        owner_user_id=user_id,
        db_id=conv.get("db_id"),
        db_kind="none" if classification == "none" else "sqlite_file",
        title=conv.get("title"),
        payload_json=payload.model_dump_json(),
        created_at=now,
        expires_at=expires,
    )

    return SharedSnapshotMeta(
        token=token,
        share_url=_share_url(token),
        created_at=now,
        expires_at=expires,
        revoked=False,
        view_count=0,
    )
