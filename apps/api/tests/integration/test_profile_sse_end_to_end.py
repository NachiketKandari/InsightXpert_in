"""End-to-end SSE test for POST /databases/{db_id}/profile.

The profile run is driven against the bundled ``toxicology.sqlite`` (11 cols,
4 tables) so the whole stream completes in well under a second. The LLM is
mocked with an ``AsyncMock`` that returns a well-formed JSON-object-per-batch
response so no network / Gemini key is needed.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


def _parse_sse_stream(text: str) -> list[dict]:
    """Parse the body of a TestClient SSE response into a list of payloads.

    sse-starlette prefixes each event with ``data: ``. ``[DONE]`` is the
    terminal sentinel — we drop it.
    """
    events: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        body = line[len("data: ") :]
        if body == "[DONE]":
            break
        events.append(json.loads(body))
    return events


@pytest.fixture
def fake_llm_ok():
    """AsyncMock LLM returning a well-formed JSON response covering every column
    named in the incoming prompt. Works for both the batched summary and
    batched quirks prompt shapes.
    """
    llm = AsyncMock()

    async def _answer(prompt: str) -> str:
        names = [
            line.split("column_name:", 1)[1].strip()
            for line in prompt.splitlines()
            if "column_name:" in line
        ]
        if "quirks" in prompt.lower():
            return json.dumps(
                {n: {"quirks": [f"phrase for {n}"]} for n in names}
            )
        return json.dumps(
            {
                n: {
                    "short_summary": f"short for {n}",
                    "long_summary": f"long for {n}",
                }
                for n in names
            }
        )

    llm.async_generate = AsyncMock(side_effect=_answer)
    return llm


def _bundled_databases_dir() -> str:
    from pathlib import Path

    # This test file lives at apps/api/tests/integration/…; walk up to apps/api
    return str(Path(__file__).resolve().parents[2] / "Databases")


def test_profile_cost_gate_closes_stream_without_run(authed_client: TestClient, tmp_path, monkeypatch):
    """confirmed=false + flags on → exactly one profile_cost_estimate chunk."""
    r = authed_client.post(
        "/api/v1/databases/toxicology/profile",
        json={"with_summaries": True, "with_quirks": True, "confirmed": False},
    )
    assert r.status_code == 200, r.text
    events = _parse_sse_stream(r.text)
    # One cost-estimate chunk, then [DONE] (which _parse_sse_stream drops).
    types = [e["type"] for e in events]
    assert types == ["profile_cost_estimate"], types
    payload = events[0]["data"]
    # toxicology has 11 columns × (summaries + quirks) = 2 batches of 11 cols.
    # With batch_size=20 that's ceil(11/20)=1 call each → 2 total.
    assert payload["columns"] == 11
    assert payload["batch_size"] == 20
    assert payload["total_llm_calls"] == 2
    assert payload["estimated_seconds"] >= 10


def test_profile_sse_end_to_end_confirmed(authed_client: TestClient, fake_llm_ok):
    """With confirmed=true and every flag on, the 7 stages must emit
    start/complete in order and conclude with profile_done.
    """
    # Inject the mock LLM onto app.state so the route's LLM-resolve path
    # picks it up without constructing a real GeminiLLM.
    authed_client.app.state.llm = fake_llm_ok

    r = authed_client.post(
        "/api/v1/databases/toxicology/profile",
        json={
            "with_summaries": True,
            "with_quirks": True,
            "with_lsh": True,
            "with_vectors": True,
            "confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    events = _parse_sse_stream(r.text)
    types = [e["type"] for e in events]

    # Expected contract: for each of the 6 stages, a started/completed pair,
    # then profile_done. Order must match STAGE_ORDER.
    expected_stages = ["schema", "stats", "join_graph", "summaries", "quirks", "lsh", "vectors", "table_descriptions"]
    stage_starts = [
        e["data"]["stage"] for e in events if e["type"] == "profile_stage_started"
    ]
    stage_completes = [
        e["data"]["stage"] for e in events if e["type"] == "profile_stage_completed"
    ]
    assert stage_starts == expected_stages, stage_starts
    assert stage_completes == expected_stages, stage_completes
    assert types[-1] == "profile_done", types

    done = events[-1]["data"]
    assert done["db_id"] == "toxicology"
    assert done["table_count"] == 4
    assert done["column_count"] == 11
    # with_summaries was on and the mock populated every column.
    assert done["summaries_populated"] == 11


def test_profile_schema_stats_only_no_llm(authed_client: TestClient):
    """All flags off → no cost-gate, no LLM needed, still emits 7 stage pairs
    (summaries/quirks/lsh/vectors/table_descriptions are marked note='skipped').
    """
    r = authed_client.post(
        "/api/v1/databases/toxicology/profile",
        json={"confirmed": True},
    )
    assert r.status_code == 200, r.text
    events = _parse_sse_stream(r.text)
    starts = [e["data"]["stage"] for e in events if e["type"] == "profile_stage_started"]
    assert starts == ["schema", "stats", "join_graph", "summaries", "quirks", "lsh", "vectors", "table_descriptions"]
    # Skipped stages carry note='skipped'
    skipped = [
        e["data"]
        for e in events
        if e["type"] == "profile_stage_completed" and e["data"].get("note") == "skipped"
    ]
    assert [s["stage"] for s in skipped] == ["summaries", "quirks", "lsh", "vectors", "table_descriptions"]
    assert events[-1]["type"] == "profile_done"
