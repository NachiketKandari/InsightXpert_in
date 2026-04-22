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


def test_upload_collision_blocks_bundled_overwrite(authed_client: TestClient):
    """MF-PR-4: a user cannot upload over a bundled-public db_id (toxicology,
    california_schools) — the visibility row is public/owner-null and must
    be protected. The route 409s BEFORE reading the body."""
    data = _make_sqlite_bytes()
    r = authed_client.post(
        "/api/v1/databases/upload",
        data={"db_id": "toxicology"},
        files={"file": ("x.sqlite", io.BytesIO(data), "application/octet-stream")},
    )
    assert r.status_code == 409, r.text
    assert "already" in r.json()["detail"].lower()


def test_upload_idempotent_for_same_owner(authed_client: TestClient):
    """MF-PR-4 companion: re-upload by the SAME owner must still work so
    users can refresh their own DB without a 409."""
    data = _make_sqlite_bytes()
    for _ in range(2):
        r = authed_client.post(
            "/api/v1/databases/upload",
            data={"db_id": "test_reup"},
            files={"file": ("x.sqlite", io.BytesIO(data), "application/octet-stream")},
        )
        assert r.status_code == 200, r.text


def test_upload_rejects_oversize(authed_client: TestClient, monkeypatch):
    """MF-PR-1: a file larger than max_upload_mb gets 413 without being
    fully read into memory. We monkeypatch the cap down to 1 byte so a tiny
    valid SQLite payload trips it; the server should 413 after peeking the
    first chunk rather than buffering the rest."""
    from insightxpert_api.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_upload_mb", 0)  # anything > 0 bytes → 413
    data = _make_sqlite_bytes()
    r = authed_client.post(
        "/api/v1/databases/upload",
        data={"db_id": "test_oversize"},
        files={"file": ("x.sqlite", io.BytesIO(data), "application/octet-stream")},
    )
    assert r.status_code == 413, r.text


def test_upload_rejects_empty_body(authed_client: TestClient):
    """MF-PR-2 companion: empty file body must 400 (not 200 with a 0-byte
    save), because the magic-byte check otherwise slides through."""
    r = authed_client.post(
        "/api/v1/databases/upload",
        data={"db_id": "test_empty"},
        files={"file": ("empty.sqlite", io.BytesIO(b""), "application/octet-stream")},
    )
    assert r.status_code == 400


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


def test_upload_rejects_path_traversal_db_id(authed_client: TestClient):
    data = _make_sqlite_bytes()
    r = authed_client.post(
        "/api/v1/databases/upload",
        data={"db_id": "../etc/passwd"},
        files={"file": ("x.sqlite", io.BytesIO(data), "application/octet-stream")},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_db_id"


@pytest.mark.parametrize(
    "bad_db_id",
    [
        "../etc/passwd",
        "foo bar",  # space
        "UPPERCASE",
        "",  # empty
        "a" * 100,  # too long
        "_leading_underscore",  # must start alnum
        "-leading-hyphen",  # must start alnum
    ],
)
def test_upload_rejects_invalid_db_id(authed_client: TestClient, bad_db_id: str):
    data = _make_sqlite_bytes()
    r = authed_client.post(
        "/api/v1/databases/upload",
        data={"db_id": bad_db_id},
        files={"file": ("x.sqlite", io.BytesIO(data), "application/octet-stream")},
    )
    # Empty string hits the Form(...) required check first → 422. Every other
    # invalid value must reach our validator and get 400 invalid_db_id.
    if bad_db_id == "":
        assert r.status_code in (400, 422)
    else:
        assert r.status_code == 400
        assert r.json()["detail"] == "invalid_db_id"


@pytest.mark.skipif(
    True,
    reason="Real profile SSE run is covered by test_profiler_stage.py (Gemini-gated)",
)
def test_profile_sse_run(authed_client: TestClient):  # pragma: no cover
    pass
