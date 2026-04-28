"""Integration test: profiling completion triggers sample-questions generation."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _parse_sse_stream(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        body = line[len("data: "):]
        if body == "[DONE]":
            break
        events.append(json.loads(body))
    return events


@pytest.mark.asyncio
async def test_profile_completion_triggers_sample_questions(authed_client: TestClient, monkeypatch):
    """After a profile run completes, enqueue_sample_questions_job is scheduled."""
    called = {"n": 0}

    async def fake_enqueue(**kwargs):
        called["n"] += 1

    monkeypatch.setattr(
        "insightxpert_api.routes.databases.enqueue_sample_questions_job",
        fake_enqueue,
    )

    # Use toxicology (bundled DB, no LLM needed for schema+stats)
    r = authed_client.post(
        "/api/v1/databases/toxicology/profile",
        json={"confirmed": True},
    )
    assert r.status_code == 200, r.text
    events = _parse_sse_stream(r.text)
    # Profile run completes
    assert any(e["type"] == "profile_done" for e in events)
    # The sample-questions job was enqueued (via asyncio.create_task inside _run_profile_v2)
    assert called["n"] >= 1
