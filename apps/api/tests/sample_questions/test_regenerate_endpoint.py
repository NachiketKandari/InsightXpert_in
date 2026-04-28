"""Tests for POST /api/v1/databases/{db_id}/sample-questions/regenerate
and for the sample_questions field in GET /api/v1/databases/{db_id}/profile.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.profiling import repository as profiles_repo
from insightxpert_api.sample_questions import repository as sq_repo


@pytest.fixture
def seeded_profile_authed(authed_client, fresh_db):
    """Seed a profile row so both the regenerate and GET-profile endpoints have data."""
    profiles_repo.upsert(
        db_id="test-db", profile_kind="base",
        owner_user_id="any", generated_by="any",
        profile_json='{"db_id":"test-db","tables":[{"name":"x","row_count":1,"columns":[{"name":"y","type":"INTEGER","stats":{"count":1,"null_count":0,"distinct_count":1}}]}]}',
    )
    return authed_client


@pytest.mark.asyncio
async def test_regenerate_returns_202_and_enqueues(seeded_profile_authed, monkeypatch):
    called = {"n": 0}

    async def fake(*a, **k):
        called["n"] += 1

    monkeypatch.setattr(
        "insightxpert_api.routes.databases.enqueue_sample_questions_job", fake,
    )
    resp = seeded_profile_authed.post("/api/v1/databases/test-db/sample-questions/regenerate")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] in {"pending", "ok", "fallback", "failed"}
    assert called["n"] == 1


def test_get_profile_includes_sample_questions_field(seeded_profile_authed):
    """GET /profile returns sample_questions key (null when not yet generated)."""
    resp = seeded_profile_authed.get("/api/v1/databases/test-db/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert "sample_questions" in body
    # Not yet generated, so it's null
    assert body["sample_questions"] is None
