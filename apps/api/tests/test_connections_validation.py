"""Pydantic validation + redaction tests for connections.types."""

from __future__ import annotations

import pytest


def test_postgres_connection_parses_dsn():
    from insightxpert_api.connections.types import PostgresConnection

    pc = PostgresConnection(
        host="db.example.com",
        port=5432,
        database="prod",
        username="ro_user",
        password="secret",
        ssl_mode="require",
        schema="analytics",
    )
    dsn = pc.to_dsn()
    assert "postgresql+psycopg://ro_user" in dsn
    assert "secret" in dsn
    assert "sslmode=require" in dsn


def test_postgres_connection_redacts_password_in_repr():
    from insightxpert_api.connections.types import PostgresConnection

    pc = PostgresConnection(
        host="h", database="d", username="u", password="topsecret"
    )
    assert "topsecret" not in repr(pc)
    assert "***" in repr(pc)


def test_postgres_url_encodes_special_chars():
    from insightxpert_api.connections.types import PostgresConnection

    pc = PostgresConnection(
        host="h", database="d", username="u", password="p@ss/word"
    )
    dsn = pc.to_dsn()
    # Raw '@' / '/' from the password must not appear unencoded.
    assert "p@ss/word" not in dsn
    assert "p%40ss%2Fword" in dsn


def test_libsql_connection_validates_url():
    from insightxpert_api.connections.types import LibsqlConnection

    with pytest.raises(ValueError, match="libsql://"):
        LibsqlConnection(url="https://wrong.scheme", auth_token="t")


def test_libsql_connection_redacts_token():
    from insightxpert_api.connections.types import LibsqlConnection

    lc = LibsqlConnection(url="libsql://x.turso.io", auth_token="hunter2")
    assert "hunter2" not in repr(lc)
    assert "***" in repr(lc)
