"""Tests for the unified connector dispatch (resolve_connector)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_dispatch_sqlite_file_returns_database_connector(tmp_path):
    from insightxpert_api.db.connector import DatabaseConnector, resolve_connector

    db = tmp_path / "x.sqlite"
    db.write_bytes(b"")  # path just has to exist for construction
    c = resolve_connector(kind="sqlite_file", db_path=str(db))
    assert isinstance(c, DatabaseConnector)


def test_dispatch_sqlite_file_requires_path():
    from insightxpert_api.db.connector import resolve_connector

    with pytest.raises(ValueError, match="db_path"):
        resolve_connector(kind="sqlite_file")


def test_dispatch_postgres_uses_postgres_connector():
    from insightxpert_api.connections.types import PostgresConnection
    from insightxpert_api.db.connector import resolve_connector

    cfg = PostgresConnection(host="h", database="d", username="u", password="p")
    with patch(
        "insightxpert_api.connections.postgres_connector.PostgresConnector"
    ) as PC:
        resolve_connector(kind="postgres", config=cfg)
        PC.assert_called_once_with(cfg)


def test_dispatch_postgres_requires_typed_config():
    from insightxpert_api.db.connector import resolve_connector

    with pytest.raises(ValueError, match="PostgresConnection"):
        resolve_connector(kind="postgres", config={"host": "h"})


def test_dispatch_libsql_not_implemented():
    from insightxpert_api.db.connector import resolve_connector

    with pytest.raises(NotImplementedError):
        resolve_connector(kind="libsql")


def test_dispatch_unknown_kind_raises():
    from insightxpert_api.db.connector import resolve_connector

    with pytest.raises(ValueError, match="unsupported"):
        resolve_connector(kind="snowflake")
