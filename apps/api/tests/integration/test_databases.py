"""Integration tests for the /databases routes.

Covers listing bundled DBs, uploading (happy + rejected), schema DDL, and the
404 path for unprofiled databases. The actual profile SSE run is gated on a
real Gemini key (see test_profiler_stage.py) and skipped in CI — we don't
duplicate that here.
"""

from __future__ import annotations

import io
import sqlite3

import pytest
from fastapi.testclient import TestClient


def _make_sqlite_bytes() -> bytes:
    """Build an in-memory SQLite file and return its serialized bytes."""
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT NOT NULL);
        INSERT INTO widgets(id, label) VALUES (1,'a'),(2,'b');
        """
    )
    con.commit()
    # sqlite3.Connection.serialize is Python 3.11+.
    blob = con.serialize()
    con.close()
    return bytes(blob)


def test_list_databases_returns_bundled(authed_client: TestClient):
    r = authed_client.get("/api/v1/databases")
    assert r.status_code == 200
    items = r.json()
    db_ids = [it["db_id"] for it in items]
    # california_schools is in Databases/ per plan's invariant.
    assert "california_schools" in db_ids
    assert all(it["source"] in ("bundled", "uploaded") for it in items)


def test_upload_sqlite_roundtrip(authed_client: TestClient):
    data = _make_sqlite_bytes()
    r = authed_client.post(
        "/api/v1/databases/upload",
        data={"db_id": "test_upload"},
        files={"file": ("test.sqlite", io.BytesIO(data), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"db_id": "test_upload", "source": "uploaded"}

    # Subsequent list includes it.
    r2 = authed_client.get("/api/v1/databases")
    assert r2.status_code == 200
    assert "test_upload" in [it["db_id"] for it in r2.json()]


def test_upload_rejects_non_sqlite(authed_client: TestClient):
    r = authed_client.post(
        "/api/v1/databases/upload",
        data={"db_id": "bogus"},
        files={"file": ("fake.sqlite", io.BytesIO(b"not a sqlite file"), "text/plain")},
    )
    assert r.status_code == 400


def test_schema_returns_ddl(authed_client: TestClient):
    r = authed_client.get("/api/v1/databases/california_schools/schema")
    assert r.status_code == 200
    body = r.json()
    assert "CREATE TABLE" in body["ddl"].upper()
    assert isinstance(body["tables"], list) and body["tables"]


def test_profile_404_when_unprofiled(authed_client: TestClient):
    # Fresh session → no cached profile for any bundled DB.
    r = authed_client.get("/api/v1/databases/california_schools/profile")
    assert r.status_code == 404


@pytest.mark.skipif(
    True,
    reason="Real profile SSE run is covered by test_profiler_stage.py (Gemini-gated)",
)
def test_profile_sse_run(authed_client: TestClient):  # pragma: no cover
    pass
