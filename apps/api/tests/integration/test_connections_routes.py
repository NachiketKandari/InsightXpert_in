"""Integration tests for /api/v1/connections — test, create, list, delete."""

from __future__ import annotations

from unittest.mock import patch

import pytest


_TEST_KEY = "GbhRElFcz5W3rC9V8a4GQYoT3p6jZCqZ4EQRQyGzwYY="


@pytest.fixture
def encryption_env(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", _TEST_KEY)
    from insightxpert_api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


_PG_BODY = {
    "db_id": "my_prod_pg",
    "kind": "postgres",
    "config": {
        "host": "db.example.com",
        "port": 5432,
        "database": "prod",
        "username": "ro",
        "password": "secret",
        "ssl_mode": "require",
        "schema": "public",
    },
}


def test_test_endpoint_calls_postgres_connector(user_client, encryption_env):
    client, _ = user_client
    with patch(
        "insightxpert_api.routes.connections.PostgresConnector"
    ) as PC:
        PC.return_value.list_tables.return_value = ["users", "orders"]
        r = client.post("/api/v1/connections/test", json=_PG_BODY)
    assert r.status_code == 200, r.text
    assert r.json()["tables"] == ["users", "orders"]


def test_create_then_list_then_delete(user_client, encryption_env):
    client, _ = user_client
    s = client.post("/api/v1/connections", json=_PG_BODY)
    assert s.status_code == 201, s.text

    listed = client.get("/api/v1/connections")
    assert listed.status_code == 200
    ids = [d["db_id"] for d in listed.json()]
    assert "my_prod_pg" in ids

    d = client.delete("/api/v1/connections/my_prod_pg")
    assert d.status_code == 204

    listed2 = client.get("/api/v1/connections")
    ids2 = [d["db_id"] for d in listed2.json()]
    assert "my_prod_pg" not in ids2


def test_password_never_returned_in_list(user_client, encryption_env):
    client, _ = user_client
    body = {
        "db_id": "leak_check_pg",
        "kind": "postgres",
        "config": {
            "host": "h",
            "database": "d",
            "username": "u",
            "password": "topsecretvalue",
            "ssl_mode": "require",
            "schema": "public",
        },
    }
    client.post("/api/v1/connections", json=body)
    r = client.get("/api/v1/connections")
    assert "topsecretvalue" not in r.text


def test_invalid_kind_400(user_client, encryption_env):
    client, _ = user_client
    bad = {**_PG_BODY, "kind": "snowflake"}
    r = client.post("/api/v1/connections", json=bad)
    assert r.status_code == 400


def test_libsql_test_returns_501(user_client, encryption_env):
    client, _ = user_client
    body = {
        "db_id": "ls",
        "kind": "libsql",
        "config": {"url": "libsql://x.turso.io", "auth_token": "t"},
    }
    r = client.post("/api/v1/connections/test", json=body)
    assert r.status_code == 501


def test_delete_other_owner_forbidden(user_client, encryption_env):
    """A user can't delete a connection owned by someone else."""
    from insightxpert_api.databases import repository as repo

    client, _ = user_client
    # Plant a row owned by a different user.
    repo.insert_db(
        "someone_elses_pg",
        "other-user-id",
        "private",
        0,
        kind="postgres",
        connection_config_encrypted="x",
    )
    r = client.delete("/api/v1/connections/someone_elses_pg")
    assert r.status_code == 403
