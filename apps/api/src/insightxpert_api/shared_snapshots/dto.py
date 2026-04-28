"""Pydantic DTOs for the shared-snapshots feature.

Three boundaries:

* :class:`SharedSnapshotMessage` / :class:`SharedSnapshotPayload` — the
  *frozen* viewable content. Stored as JSON in
  ``shared_snapshots.payload_json``. Deliberately small — no agent
  traces, no enrichment traces, no insights, no internal IDs.
* :class:`SharedSnapshotPublic` — what the public viewer endpoint
  returns. Strictly a subset of the payload plus a couple of presentation
  fields. NEVER includes ``conversation_id``, ``owner_user_id``, or
  ``db_id``.
* :class:`SharedSnapshotMeta` — what the owner sees about their own
  share (token, share_url, expiry, revoked flag, view_count).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SharedSnapshotMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    created_at: int


class SharedSnapshotPayload(BaseModel):
    """Frozen content. Stored as JSON in ``payload_json``."""

    model_config = ConfigDict(extra="forbid")

    title: str | None
    dataset_name: str | None
    messages: list[SharedSnapshotMessage]


class SharedSnapshotPublic(BaseModel):
    """Response for ``GET /api/v1/public/shares/{token}`` — no auth."""

    model_config = ConfigDict(extra="forbid")

    title: str | None
    dataset_name: str | None
    messages: list[SharedSnapshotMessage]
    created_at: int
    expires_at: int | None


class SharedSnapshotMeta(BaseModel):
    """Owner-facing metadata; returned by share-create / share-get."""

    model_config = ConfigDict(extra="forbid")

    token: str
    share_url: str
    created_at: int
    expires_at: int | None
    revoked: bool
    view_count: int
