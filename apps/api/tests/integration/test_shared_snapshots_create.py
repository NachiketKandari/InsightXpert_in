"""Repository-level tests for shared_snapshots."""
from __future__ import annotations

import time

import pytest

from insightxpert_api.shared_snapshots import repository as repo


def test_insert_then_get_roundtrip(fresh_db):
    token = "tok_test_roundtrip_" + str(int(time.time() * 1000))
    repo.insert(
        token=token,
        conversation_id="c-roundtrip",
        owner_user_id="u-roundtrip",
        db_id="bundled_demo",
        db_kind="sqlite_file",
        title="Demo",
        payload_json='{"messages":[]}',
        created_at=1700000000,
        expires_at=1700000000 + 90 * 86400,
    )

    row = repo.get_by_token(token)
    assert row is not None
    assert row["conversation_id"] == "c-roundtrip"
    assert row["owner_user_id"] == "u-roundtrip"
    assert row["payload_json"] == '{"messages":[]}'
    assert row["revoked_at"] is None


def test_revoke_sets_timestamp(fresh_db):
    token = "tok_test_revoke_" + str(int(time.time() * 1000))
    repo.insert(
        token=token,
        conversation_id="c-rev",
        owner_user_id="u-rev",
        db_id=None,
        db_kind="sqlite_file",
        title=None,
        payload_json='{}',
        created_at=1700000000,
        expires_at=None,
    )
    repo.revoke(token)
    row = repo.get_by_token(token)
    assert row is not None
    assert row["revoked_at"] is not None and row["revoked_at"] > 0
