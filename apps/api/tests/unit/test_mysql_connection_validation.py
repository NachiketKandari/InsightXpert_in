"""Unit tests for MySQLConnection Pydantic model."""

from __future__ import annotations

import pytest

from insightxpert_api.connections.types import MySQLConnection


def test_defaults():
    cfg = MySQLConnection(host="h", database="d", username="u", password="p")
    assert cfg.kind == "mysql"
    assert cfg.port == 3306
    assert cfg.charset == "utf8mb4"
    assert cfg.ssl_enabled is True


def test_to_dsn_basic():
    cfg = MySQLConnection(host="db.example.com", database="analytics", username="reader", password="s3cret")
    dsn = cfg.to_dsn()
    assert dsn == "mysql+pymysql://reader:s3cret@db.example.com:3306/analytics?charset=utf8mb4"


def test_to_dsn_custom_port_and_charset():
    cfg = MySQLConnection(host="h", database="d", username="u", password="p", port=3307, charset="latin1")
    dsn = cfg.to_dsn()
    assert "3307" in dsn
    assert "latin1" in dsn


def test_password_special_chars_encoded():
    cfg = MySQLConnection(host="h", database="d", username="u", password="p@ss:word!")
    dsn = cfg.to_dsn()
    # @ and : should be URL-encoded
    assert "p%40ss%3Aword%21" in dsn


def test_username_special_chars_encoded():
    cfg = MySQLConnection(host="h", database="d", username="user@domain", password="p")
    dsn = cfg.to_dsn()
    assert "user%40domain" in dsn


def test_password_redacted_in_repr():
    cfg = MySQLConnection(host="h", database="d", username="u", password="super_secret_123")
    r = repr(cfg)
    assert "super_secret_123" not in r
    assert "***" in r
    assert "MySQLConnection" in r


def test_repr_includes_non_secret_fields():
    cfg = MySQLConnection(host="myhost", database="mydb", username="myuser", password="p")
    r = repr(cfg)
    assert "myhost" in r
    assert "mydb" in r
    assert "myuser" in r


def test_ssl_disabled():
    cfg = MySQLConnection(host="h", database="d", username="u", password="p", ssl_enabled=False)
    assert cfg.ssl_enabled is False
