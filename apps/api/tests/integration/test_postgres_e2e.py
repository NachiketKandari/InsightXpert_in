"""End-to-end Postgres pipeline test.

Gated on:
* ``DATABASE_URL_TOXICOLOGY_PG`` — the Supabase (or other Postgres) connection
  string pointing at a database with the BIRD ``toxicology`` tables loaded in
  a ``toxicology`` schema. Run ``scripts/seed-toxicology-postgres.sh`` once to
  populate this.
* ``GEMINI_API_KEY_REAL`` — real Gemini key; conftest otherwise injects a
  test-key that would not answer a live prompt.

Both skip gates must be passing for this module to execute. Mirrors the
real-Gemini pattern in tests/integration/test_end_to_end.py.

Run::

    GEMINI_API_KEY_REAL=<key> \\
      uv run pytest tests/integration/test_postgres_e2e.py -v -s
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from insightxpert_api.config import get_settings
from insightxpert_api.main import create_app

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "Databases"
_DB_ID = "toxicology_pg"

requires_pg = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_TOXICOLOGY_PG"),
    reason="needs DATABASE_URL_TOXICOLOGY_PG + seeded toxicology schema",
)
requires_real_gemini = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY_REAL"),
    reason="needs a real Gemini API key (GEMINI_API_KEY_REAL)",
)


@pytest.fixture
def real_client(monkeypatch: pytest.MonkeyPatch, fresh_db) -> TestClient:
    """TestClient with real Gemini + real Postgres query-target configured."""
    from insightxpert_api.users import service as users_service
    from insightxpert_api.users.models import CreateUserInput

    monkeypatch.setenv("GEMINI_API_KEY", os.environ["GEMINI_API_KEY_REAL"])
    monkeypatch.setenv("BUNDLED_DBS_DIR", str(BUNDLED_DIR))
    monkeypatch.setenv("SESSION_SECRET", "s" * 32)
    # DATABASE_URL_TOXICOLOGY_PG is already in the process env per the requires_pg gate;
    # DatabaseService reads it at list() time, no config clear needed there.
    get_settings.cache_clear()

    invited = users_service.invite(
        CreateUserInput(email="pg-e2e@example.com", role="user")
    )
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "pg-e2e@example.com", "password": invited.temp_password},
    )
    assert r.status_code == 200
    return client


@pytest.mark.slow
@requires_pg
@requires_real_gemini
def test_toxicology_pg_appears_in_databases_list(real_client: TestClient):
    r = real_client.get("/api/v1/databases")
    assert r.status_code == 200, r.text
    db_ids = {d["db_id"] for d in r.json()}
    assert _DB_ID in db_ids, f"expected {_DB_ID} in {sorted(db_ids)}"


@pytest.mark.slow
@requires_pg
@requires_real_gemini
def test_sql_execute_direct_against_postgres(real_client: TestClient):
    """Pure SQL path, no LLM — exercises DialectAdapter.open_readonly on Postgres."""
    r = real_client.post(
        "/api/v1/sql/execute",
        json={
            "db_id": _DB_ID,
            "sql": "SELECT COUNT(*) AS n FROM toxicology.molecule",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["n"]
    assert body["row_count"] == 1
    assert isinstance(body["rows"][0][0], int)
    assert body["rows"][0][0] > 0


@pytest.mark.slow
@requires_pg
@requires_real_gemini
def test_pipeline_chat_answer_against_postgres(real_client: TestClient):
    """Full pipeline: natural-language question → Postgres-dialect SQL → answer.

    Proves the adapter wiring reaches every stage (validator, generator, executor,
    refiner). Uses a simple count-style question that any sane model will answer.
    """
    r = real_client.post(
        "/api/v1/chat/answer",
        json={
            "message": "How many molecules are in the database?",
            "db_id": _DB_ID,
        },
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get("answer"), str) and len(body["answer"]) > 0
    assert isinstance(body.get("sql"), list) and len(body["sql"]) >= 1
    # Postgres-flavored SQL expected: schema-qualified name, no SQLite PRAGMAs.
    joined = " ".join(body["sql"]).lower()
    assert "molecule" in joined, body["sql"]
    assert "pragma" not in joined
