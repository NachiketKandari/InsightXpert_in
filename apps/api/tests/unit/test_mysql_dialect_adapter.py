"""Unit tests for MySQL dialect adapter and connector dispatch."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from insightxpert_api.db.connector import resolve_connector
from insightxpert_api.db.dialects import get_adapter
from insightxpert_api.db.dialects.mysql import MysqlAdapter


def test_mysql_adapter_registered():
    adapter = get_adapter("mysql")
    assert isinstance(adapter, MysqlAdapter)


def test_mysql_adapter_has_correct_metadata():
    adapter = get_adapter("mysql")
    assert adapter.name == "mysql"
    assert adapter.sqlglot_dialect == "mysql"
    assert adapter.prompt_variant == "mysql"
    assert isinstance(adapter.forbidden_sql_re, re.Pattern)


def test_mysql_adapter_profiling_queries():
    adapter = get_adapter("mysql")
    pq = adapter.profiling_queries()
    assert pq.null_count
    assert pq.distinct_count
    assert pq.min_max
    assert pq.sample_rows
    assert "RAND()" in pq.sample_rows  # No TABLESAMPLE in MySQL


def test_mysql_adapter_is_timeout_error():
    import pymysql

    adapter = get_adapter("mysql")

    # Real pymysql OperationalError with timeout message
    timeout_err = pymysql.err.OperationalError(2003, "Can't connect to MySQL server on 'localhost' (timed out)")
    assert adapter.is_timeout_error(timeout_err) is True

    # Lost connection
    lost_conn = pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")
    assert adapter.is_timeout_error(lost_conn) is True

    # Server gone away
    gone = pymysql.err.OperationalError(2006, "MySQL server has gone away")
    assert adapter.is_timeout_error(gone) is True

    # Non-timeout errors
    assert adapter.is_timeout_error(ValueError("something else")) is False
    assert adapter.is_timeout_error(RuntimeError("random")) is False


def test_resolve_connector_dispatches_to_mysql():
    from insightxpert_api.connections.types import MySQLConnection

    cfg = MySQLConnection(host="h", database="d", username="u", password="p")
    connector = resolve_connector(kind="mysql", config=cfg)

    from insightxpert_api.connections.mysql_connector import MySQLConnector

    assert isinstance(connector, MySQLConnector)


def test_resolve_connector_mysql_requires_config():
    with pytest.raises(ValueError, match="MySQLConnection config"):
        resolve_connector(kind="mysql", config="not_a_config")


def test_resolve_connector_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unsupported db kind"):
        resolve_connector(kind="cassandra")
