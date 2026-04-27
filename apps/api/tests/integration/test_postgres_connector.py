"""Integration tests for PostgresConnector — gated on TEST_PG_URL.

Run a throwaway Postgres for these tests::

    docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=ix_test --name ix_pg_test postgres:16
    sleep 3
    TEST_PG_URL="postgres://postgres:test@localhost:55432/ix_test" \\
        uv run pytest tests/integration/test_postgres_connector.py -v
"""

from __future__ import annotations

import os
import urllib.parse

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_PG_URL"),
    reason="TEST_PG_URL required (e.g. local docker postgres)",
)


def _config():
    from insightxpert_api.connections.types import PostgresConnection

    u = urllib.parse.urlparse(os.environ["TEST_PG_URL"])
    return PostgresConnection(
        host=u.hostname or "localhost",
        port=u.port or 5432,
        database=(u.path or "/").lstrip("/"),
        username=u.username or "",
        password=u.password or "",
        ssl_mode="disable",
    )


def test_select_returns_rows():
    from insightxpert_api.connections.postgres_connector import PostgresConnector

    c = PostgresConnector(_config())
    result = c.execute("SELECT 1 AS n")
    assert result.columns == ["n"]
    assert result.rows == [(1,)]


def test_regex_blocks_obvious_writes():
    from insightxpert_api.connections.postgres_connector import PostgresConnector

    c = PostgresConnector(_config())
    with pytest.raises(ValueError, match="read-only"):
        c.execute("INSERT INTO x VALUES (1)")


def test_session_guard_catches_create_temp_table():
    """Even if regex misses (it doesn't here), the session-level read-only
    guard must reject the write before commit."""
    from insightxpert_api.connections.postgres_connector import PostgresConnector

    c = PostgresConnector(_config())
    with pytest.raises(Exception):
        c.execute("CREATE TEMP TABLE x AS SELECT 1")


def test_list_tables():
    from insightxpert_api.connections.postgres_connector import PostgresConnector

    c = PostgresConnector(_config())
    # information_schema is always available; the call should at least not error.
    tables = c.list_tables()
    assert isinstance(tables, list)
