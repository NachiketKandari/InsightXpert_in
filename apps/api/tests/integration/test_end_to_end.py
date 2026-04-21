"""End-to-end smoke test: real pipeline against a bundled BIRD SQLite sample.

Gated on ``GEMINI_API_KEY_REAL`` — the auto-injected ``GEMINI_API_KEY=test-key`` from
conftest keeps the rest of the suite offline, but this test wants a real key. Run:

    GEMINI_API_KEY_REAL=<your-key> uv run pytest tests/integration/test_end_to_end.py -v -s

This is the canary that the full stack works on your machine before deploying.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.config import get_settings
from insightxpert_api.main import create_app

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "Databases"
_DB_ID = "california_schools"

requires_real_gemini = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY_REAL"),
    reason="needs a real Gemini API key (GEMINI_API_KEY_REAL)",
)


@pytest.fixture
def real_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient configured with the real Gemini key + bundled DBs dir."""
    real_key = os.environ["GEMINI_API_KEY_REAL"]
    monkeypatch.setenv("GEMINI_API_KEY", real_key)
    monkeypatch.setenv("BUNDLED_DBS_DIR", str(BUNDLED_DIR))
    monkeypatch.setenv("GATE_PASSWORD", "test-pw")
    monkeypatch.setenv("SESSION_SECRET", "s" * 32)
    get_settings.cache_clear()

    client = TestClient(create_app())
    r = client.post("/api/v1/auth/unlock", json={"password": "test-pw"})
    assert r.status_code == 200
    return client


@pytest.mark.slow
@requires_real_gemini
def test_e2e_chat_answer_against_california_schools(real_client: TestClient):
    """End-to-end: question in → SQL generated + executed + answer out."""
    assert (BUNDLED_DIR / f"{_DB_ID}.sqlite").exists(), (
        "bundled DB missing; run apps/api/scripts/fetch-bundled-dbs.sh"
    )

    r = real_client.post(
        "/api/v1/chat/answer",
        json={"message": "How many schools are in the database?", "db_id": _DB_ID},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("conversation_id")
    assert isinstance(body.get("answer"), str) and len(body["answer"]) > 0
    assert isinstance(body.get("sql"), list) and len(body["sql"]) >= 1
    # Sanity: the generated SQL should reference the `schools` table somewhere.
    assert any("schools" in s.lower() for s in body["sql"]), body["sql"]


@pytest.mark.slow
@requires_real_gemini
def test_e2e_sql_execute_direct(real_client: TestClient):
    """/sql/execute against a bundled DB — no LLM, fast canary for the exec path."""
    r = real_client.post(
        "/api/v1/sql/execute",
        json={"db_id": _DB_ID, "sql": "SELECT COUNT(*) AS n FROM schools"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["n"]
    assert body["row_count"] == 1
    assert isinstance(body["rows"][0][0], int)
    assert body["rows"][0][0] > 0
