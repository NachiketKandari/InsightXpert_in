"""Tests for POST /api/v1/sql/execute."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_sql_execute_happy_path(authed_client: TestClient):
    r = authed_client.post(
        "/api/v1/sql/execute",
        json={"db_id": "california_schools", "sql": "SELECT 1 AS n"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["n"]
    assert body["rows"] == [[1]]
    assert body["row_count"] == 1
    assert isinstance(body["execution_time_ms"], int)


def test_sql_execute_rejects_writes(authed_client: TestClient):
    r = authed_client.post(
        "/api/v1/sql/execute",
        json={"db_id": "california_schools", "sql": "DROP TABLE schools"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "sql_forbidden_write"


def test_sql_execute_syntax_error(authed_client: TestClient):
    r = authed_client.post(
        "/api/v1/sql/execute",
        json={"db_id": "california_schools", "sql": "SELECT not valid sql!!"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "sql_error"


def test_sql_execute_unknown_db(authed_client: TestClient):
    r = authed_client.post(
        "/api/v1/sql/execute",
        json={"db_id": "nope_not_here", "sql": "SELECT 1"},
    )
    assert r.status_code == 404


def test_sql_execute_requires_session(client: TestClient):
    r = client.post(
        "/api/v1/sql/execute",
        json={"db_id": "california_schools", "sql": "SELECT 1"},
    )
    assert r.status_code == 401
