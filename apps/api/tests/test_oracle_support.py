"""Oracle BYO-DB support — mock-only tests (no live Oracle required).

Covers: config validation/DSN/redaction, discovery helpers, connector
dispatch, dialect registration, query-time table-scope enforcement, schema
extraction, registry refs, and the kind CHECK constraint.
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# connections.types.OracleConnection
# ---------------------------------------------------------------------------


def _oracle_config(**overrides):
    from insightxpert_api.connections.types import OracleConnection

    base = {
        "host": "db.example.com",
        "port": 1521,
        "service_name": "ORCLPDB",
        "username": "ro_user",
        "password": "s3cret",
    }
    base.update(overrides)
    return OracleConnection(**base)


def test_oracle_dsn_shape():
    cfg = _oracle_config()
    dsn = cfg.to_dsn()
    # Service names go in the ?service_name= query form — the URL path
    # segment means SID to this dialect.
    assert dsn.startswith("oracle+oracledb://ro_user:")
    assert "@db.example.com:1521/" in dsn
    assert "service_name=ORCLPDB" in dsn
    assert "s3cret" in dsn  # DSN itself carries the secret (never logged)


def test_oracle_redacts_password_in_repr():
    cfg = _oracle_config(password="topsecret")
    assert "topsecret" not in repr(cfg)
    assert "***" in repr(cfg)


def test_oracle_rejects_empty_service_name():
    with pytest.raises(ValueError, match="service_name"):
        _oracle_config(service_name="  ")


def test_oracle_rejects_empty_host_in_fields_mode():
    with pytest.raises(ValueError, match="host"):
        _oracle_config(host="  ")


def test_oracle_connection_string_easy_connect():
    cfg = _oracle_config(
        host="", service_name="", connection_string="db.example.com:1522/ORCLPDB"
    )
    assert cfg.direct_dsn() == "db.example.com:1522/ORCLPDB"
    dsn = cfg.to_dsn()
    assert "service_name=ORCLPDB" in dsn
    assert "@db.example.com:1522/" in dsn


def test_oracle_connection_string_easy_defaults_port():
    cfg = _oracle_config(
        host="", service_name="", connection_string="db.example.com/ORCL"
    )
    assert cfg.direct_dsn() == "db.example.com:1521/ORCL"


def test_oracle_connection_string_rejects_embedded_creds():
    with pytest.raises(ValueError, match="must not contain credentials"):
        _oracle_config(
            host="",
            service_name="",
            connection_string="scott/tiger@db.example.com:1521/ORCL",
        )


def test_oracle_connection_string_requires_service():
    with pytest.raises(ValueError, match="host:1521/SERVICE"):
        _oracle_config(
            host="", service_name="", connection_string="db.example.com:1521"
        )


_DESC = (
    "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=db.example.com)(PORT=1521))"
    "(CONNECT_DATA=(SERVICE_NAME=ORCLPDB)))"
)


def test_oracle_connection_string_descriptor():
    cfg = _oracle_config(host="", service_name="", connection_string=_DESC)
    assert cfg.uses_descriptor()
    assert cfg.direct_dsn() == _DESC
    marker = cfg.to_dsn()
    assert "oracle-descriptor" in marker
    # The adapter helper recovers the exact descriptor from the marker URL.
    from insightxpert_api.db.dialects.oracle_url import split_oracle_url

    user, password, dsn = split_oracle_url(marker)
    assert (user, password, dsn) == ("ro_user", "s3cret", _DESC)


def test_oracle_connection_string_rejects_bad_descriptor():
    with pytest.raises(ValueError, match="DESCRIPTION"):
        _oracle_config(host="", service_name="", connection_string="(FOO=bar)")


def test_oracle_connection_string_exclusive_with_fields():
    with pytest.raises(ValueError, match="not both"):
        _oracle_config(connection_string="db.example.com/ORCL")


def test_split_oracle_url_service_name_form():
    from insightxpert_api.db.dialects.oracle_url import split_oracle_url

    user, password, dsn = split_oracle_url(_oracle_config().to_dsn())
    assert (user, password, dsn) == ("ro_user", "s3cret", "db.example.com:1521/ORCLPDB")


def test_oracle_connector_descriptor_uses_creator():
    from insightxpert_api.connections.oracle_connector import OracleConnector

    cfg = _oracle_config(host="", service_name="", connection_string=_DESC)
    with patch(
        "insightxpert_api.connections.oracle_connector.create_engine"
    ) as ce:
        conn = OracleConnector(cfg)
        try:
            ((url,), kwargs) = (ce.call_args.args, ce.call_args.kwargs)
            assert url == "oracle+oracledb://"
            assert callable(kwargs.get("creator"))
        finally:
            conn.dispose()


def test_oracle_effective_schema_defaults_to_user():
    cfg = _oracle_config(username="ro_user")
    assert cfg.effective_schema() == "RO_USER"


def test_oracle_effective_schema_explicit():
    cfg = _oracle_config(username="ro_user", schema="analytics")
    assert cfg.effective_schema() == "ANALYTICS"


def test_oracle_selected_tables_default_none():
    assert _oracle_config().selected_tables is None


def test_oracle_special_chars_encoded_in_dsn():
    cfg = _oracle_config(password="p@ss/word")
    assert "p@ss/word" not in cfg.to_dsn()
    assert "p%40ss%2Fword" in cfg.to_dsn()


# ---------------------------------------------------------------------------
# oracle_connector helpers
# ---------------------------------------------------------------------------


def test_base_type_strips_params():
    from insightxpert_api.connections.oracle_connector import base_type

    assert base_type("VARCHAR2(50)") == "VARCHAR2"
    assert base_type("TIMESTAMP(6) WITH TIME ZONE") == "TIMESTAMP"
    assert base_type("number") == "NUMBER"


def test_find_unsupported_columns():
    from insightxpert_api.connections.oracle_connector import find_unsupported_columns

    cols = [
        {"name": "ID", "type": "NUMBER"},
        {"name": "DOC", "type": "BLOB"},
        {"name": "SIG", "type": "RAW(16)"},
        {"name": "NOTE", "type": "CLOB"},
    ]
    bad = find_unsupported_columns(cols)
    assert bad == ["DOC: BLOB", "SIG: RAW(16)"]


def test_is_system_schema():
    from insightxpert_api.connections.oracle_connector import is_system_schema

    assert is_system_schema("SYS")
    assert is_system_schema("sys")
    assert is_system_schema("APEX_240100")
    assert not is_system_schema("ANALYTICS")
    assert not is_system_schema("RO_USER")


# ---------------------------------------------------------------------------
# dispatch (db.connector.resolve_connector)
# ---------------------------------------------------------------------------


def test_dispatch_oracle_uses_oracle_connector():
    from insightxpert_api.connections.types import OracleConnection
    from insightxpert_api.db.connector import resolve_connector

    cfg = _oracle_config()
    assert isinstance(cfg, OracleConnection)
    with patch(
        "insightxpert_api.connections.oracle_connector.OracleConnector"
    ) as oracle_cls:
        resolve_connector(kind="oracle", config=cfg)
        oracle_cls.assert_called_once_with(cfg)


def test_dispatch_oracle_requires_typed_config():
    from insightxpert_api.db.connector import resolve_connector

    with pytest.raises(ValueError, match="OracleConnection"):
        resolve_connector(kind="oracle", config={"host": "h"})


# ---------------------------------------------------------------------------
# dialect registration
# ---------------------------------------------------------------------------


def test_oracle_adapter_registered():
    from insightxpert_api.db.dialects import get_adapter

    adapter = get_adapter("oracle")
    assert adapter.name == "oracle"
    assert adapter.sqlglot_dialect == "oracle"
    assert adapter.prompt_variant == "oracle"


def test_oracle_adapter_forbids_writes():
    from insightxpert_api.db.dialects import get_adapter

    adapter = get_adapter("oracle")
    assert adapter.forbidden_sql_re.search("DROP TABLE t")
    assert adapter.forbidden_sql_re.search("SELECT * FROM t; DELETE FROM t")
    assert not adapter.forbidden_sql_re.search("SELECT a, b FROM t")


def test_oracle_profiling_pack_uses_fetch_first():
    from insightxpert_api.db.dialects import get_adapter

    pack = get_adapter("oracle").profiling_queries()
    assert "FETCH FIRST 100 ROWS ONLY" in pack.sample_rows
    assert "DBMS_RANDOM.VALUE" in pack.sample_rows
    assert "{schema}" in pack.null_count and "{table}" in pack.null_count


def test_oracle_timeout_classification():
    from insightxpert_api.db.dialects import get_adapter

    adapter = get_adapter("oracle")
    assert adapter.is_timeout_error(Exception("ORA-01013: user requested cancel"))
    assert adapter.is_timeout_error(Exception("connection timed out"))
    assert not adapter.is_timeout_error(Exception("ORA-00942: table or view does not exist"))


def test_oracle_prompt_template_exists():
    from pathlib import Path

    p = (
        Path(__file__).resolve().parent.parent
        / "src/insightxpert_api/prompts/sql_generation_oracle.j2"
    )
    text = p.read_text()
    assert "FETCH FIRST" in text
    assert "LIMIT" in text  # documents the LIMIT prohibition


def test_oracle_prompt_dispatch_and_render():
    """Generator dispatch must resolve oracle → our template, and it renders."""
    from jinja2 import Template

    from insightxpert_api.pipeline.generator_stage import _prompt_name_for_dialect

    assert _prompt_name_for_dialect("oracle") == "sql_generation_oracle"
    # sqlite keeps the un-suffixed vendored name; other dialects are suffixed.
    assert _prompt_name_for_dialect("sqlite") == "sql_generation"
    assert _prompt_name_for_dialect("postgres") == "sql_generation_postgres"

    from pathlib import Path

    tpl = Template(
        (
            Path(__file__).resolve().parent.parent
            / "src/insightxpert_api/prompts/sql_generation_oracle.j2"
        ).read_text()
    )
    out = tpl.render(question="how many?", schema_ddl="DDL", few_shot_example=None)
    assert "how many?" in out
    # No unrendered Jinja tags remain when the example block is skipped.
    assert "{%" not in out


# ---------------------------------------------------------------------------
# OracleConnector — guardrails without network
# ---------------------------------------------------------------------------


def test_oracle_connector_blocks_forbidden_sql_without_network():
    from insightxpert_api.connections.oracle_connector import OracleConnector

    conn = OracleConnector(_oracle_config())
    try:
        with pytest.raises(ValueError, match="read-only"):
            conn.execute("DROP TABLE emp")
    finally:
        conn.dispose()


def test_oracle_connector_enforces_selected_tables():
    from insightxpert_api.connections.oracle_connector import OracleConnector

    conn = OracleConnector(_oracle_config(selected_tables=["emp"]))
    try:
        with pytest.raises(ValueError, match="Access denied"):
            conn.execute("SELECT * FROM secret_table")
    finally:
        conn.dispose()


# ---------------------------------------------------------------------------
# Fake DBAPI plumbing for discovery / schema tests
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows=None, keys=()):
        self._rows = rows or []
        self._keys = list(keys)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchmany(self, n):
        return list(self._rows[:n])

    def keys(self):
        return list(self._keys)


class _FakeConnCtx:
    def __init__(self, handler):
        self._handler = handler

    def execute(self, stmt, params=None):
        return self._handler(str(stmt), params or {})

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self, handler):
        self._handler = handler
        self.disposed = False

    def connect(self):
        return _FakeConnCtx(self._handler)

    def dispose(self):
        self.disposed = True


def _discovery_handler(sql, params):
    if "FROM all_tables" in sql:
        return _FakeResult([("EMP",), ("DOCS",)])
    if "FROM all_tab_columns" in sql and "IN (" in sql:
        wanted = {v for k, v in params.items() if k.startswith("t")}
        rows = []
        if "EMP" in wanted:
            rows += [("EMP", "ID", "NUMBER", "N"), ("EMP", "NAME", "VARCHAR2", "Y")]
        if "DOCS" in wanted:
            rows += [("DOCS", "ID", "NUMBER", "N"), ("DOCS", "PAYLOAD", "BLOB", "Y")]
        return _FakeResult(rows)
    if "FROM all_tab_columns" in sql:
        name = params.get("name")
        if name == "EMP":
            return _FakeResult([("ID", "NUMBER", "N"), ("NAME", "VARCHAR2", "Y")])
        return _FakeResult([])
    if "COUNT(*)" in sql:
        return _FakeResult([(42,)])
    raise AssertionError(f"unexpected SQL: {sql[:80]}")


def test_discovery_details_flags_blob_and_counts():
    from insightxpert_api.connections.oracle_connector import OracleConnector

    with patch(
        "insightxpert_api.connections.oracle_connector.create_engine",
        return_value=_FakeEngine(_discovery_handler),
    ):
        conn = OracleConnector(_oracle_config())
        try:
            details = conn.discovery_details()
        finally:
            conn.dispose()
    by_name = {d.name: d for d in details}
    assert by_name["EMP"].row_count == 42
    assert by_name["EMP"].column_count == 2
    assert by_name["EMP"].unsupported_columns == []
    assert by_name["DOCS"].unsupported_columns == ["PAYLOAD: BLOB"]


def test_discovery_refuses_system_schema():
    from insightxpert_api.connections.oracle_connector import OracleConnector

    cfg = _oracle_config(username="u", schema="SYS")
    with patch(
        "insightxpert_api.connections.oracle_connector.create_engine",
        return_value=_FakeEngine(_discovery_handler),
    ):
        conn = OracleConnector(cfg)
        try:
            with pytest.raises(ValueError, match="system schema"):
                conn.list_tables()
        finally:
            conn.dispose()


# ---------------------------------------------------------------------------
# oracle_schema extractor with fake DBAPI
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, handler):
        self._handler = handler
        self._rows: list = []

    def execute(self, sql, params=None):
        self._rows = self._handler(sql, params or {})

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeDBAPI:
    def __init__(self, handler):
        self._handler = handler

    def cursor(self):
        return _FakeCursor(self._handler)


def _schema_handler(sql, params):
    if "FROM all_tables" in sql:
        return [("EMP",), ("DEPT",)]
    if "FROM all_tab_columns" in sql:
        if params.get("table") == "EMP":
            return [("ID", "NUMBER", "N", None), ("DEPT_ID", "NUMBER", "Y", None)]
        return [("ID", "NUMBER", "N", None)]
    if "constraint_type = 'P'" in sql:
        return [("ID",)] if params.get("table") == "EMP" else []
    if "constraint_type = 'R'" in sql:
        if params.get("table") == "EMP":
            return [("DEPT_ID", "SCH", "FK_EMP_DEPT")]
        return []
    if "constraint_name = :cname" in sql:
        return [("DEPT", "ID")]
    raise AssertionError(f"unexpected SQL: {sql[:60]}")


def test_extract_oracle_schema_tables_pks_fks():
    from insightxpert_api.db.dialects.oracle_schema import extract_oracle_schema

    schema = extract_oracle_schema(_FakeDBAPI(_schema_handler), owner="sch")
    assert [t.name for t in schema.tables] == ["EMP", "DEPT"]
    emp = schema.tables[0]
    assert [c.name for c in emp.columns] == ["ID", "DEPT_ID"]
    assert emp.columns[0].primary_key is True
    assert emp.columns[1].primary_key is False
    assert len(emp.foreign_keys) == 1
    fk = emp.foreign_keys[0]
    assert (fk.column, fk.ref_table, fk.ref_column) == ("DEPT_ID", "DEPT", "ID")


def test_extract_oracle_schema_respects_selection():
    from insightxpert_api.db.dialects.oracle_schema import extract_oracle_schema

    schema = extract_oracle_schema(
        _FakeDBAPI(_schema_handler), owner="sch", selected_tables=["dept"]
    )
    assert [t.name for t in schema.tables] == ["DEPT"]


# ---------------------------------------------------------------------------
# DatabaseConnector.execute table-scope enforcement (no network)
# ---------------------------------------------------------------------------


def _oracle_ref(**overrides):
    base = {
        "db_id": "ora1",
        "dialect": "oracle",
        "connection_url": "oracle+oracledb://u:p@h:1521/svc",
        "selected_tables": ["allowed"],
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_adapter_path_blocks_out_of_scope_table():
    from insightxpert_api.db.connector import DatabaseConnector, ForbiddenSQLError

    conn = DatabaseConnector(_oracle_ref())
    with pytest.raises(ForbiddenSQLError, match="Access denied"):
        conn.execute("SELECT * FROM secret_table")


def test_adapter_path_allows_selected_table_shape():
    """In-scope SQL must pass validation and reach the adapter (mocked)."""
    from insightxpert_api.db.connector import DatabaseConnector
    from insightxpert_api.db.dialects import get_adapter

    conn = DatabaseConnector(_oracle_ref())
    adapter = get_adapter("oracle")
    with patch.object(
        adapter, "open_readonly", side_effect=RuntimeError("sentinel")
    ), pytest.raises(RuntimeError, match="sentinel"):
        conn.execute("SELECT * FROM allowed")


def test_adapter_path_no_selection_no_scope_check():
    from insightxpert_api.db.connector import DatabaseConnector
    from insightxpert_api.db.dialects import get_adapter

    conn = DatabaseConnector(_oracle_ref(selected_tables=None))
    adapter = get_adapter("oracle")
    with patch.object(
        adapter, "open_readonly", side_effect=RuntimeError("sentinel")
    ), pytest.raises(RuntimeError, match="sentinel"):
        conn.execute("SELECT * FROM anything")


# ---------------------------------------------------------------------------
# registry: refs, kind CHECK, share refusal
# ---------------------------------------------------------------------------


def test_build_non_sqlite_refs_oracle(monkeypatch):
    from insightxpert_api.config import get_settings
    from insightxpert_api.services.database_service import DatabaseService

    monkeypatch.setenv(
        "CREDENTIAL_ENCRYPTION_KEY",
        "GbhRElFcz5W3rC9V8a4GQYoT3p6jZCqZ4EQRQyGzwYY=",
    )
    get_settings.cache_clear()
    from insightxpert_api.connections.encryption import encrypt

    config_json = _oracle_config(selected_tables=["EMP", "DEPT"]).model_dump_json(
        by_alias=True
    )
    svc = DatabaseService(bundled_dir="/nonexistent", store=object())
    row = {
        "db_id": "ora1",
        "kind": "oracle",
        "connection_config_encrypted": encrypt(config_json),
    }
    with patch.object(
        DatabaseService, "_fetch_non_sqlite_rows", return_value=[row]
    ):
        refs = svc._build_non_sqlite_refs()
    assert len(refs) == 1
    ref = refs[0]
    assert ref.dialect == "oracle"
    assert ref.connection_url.startswith("oracle+oracledb://")
    assert ref.selected_tables == ["EMP", "DEPT"]
    assert ref.owner == "RO_USER"
    assert "s3cret" not in repr(ref)


def test_kind_check_includes_oracle():
    from insightxpert_api.databases.table import databases_table

    checks = [
        c for c in databases_table.constraints if getattr(c, "name", "") == "databases_kind_check"
    ]
    assert len(checks) == 1
    assert "'oracle'" in str(checks[0].sqltext)


def test_oracle_shares_refused():
    from insightxpert_api.shared_snapshots.service import _DISALLOWED_KINDS

    assert "oracle" in _DISALLOWED_KINDS


# ---------------------------------------------------------------------------
# routes/connections.py — typed config + selection validation (mocked)
# ---------------------------------------------------------------------------


def test_build_typed_config_oracle_ok_and_invalid():
    import pytest as _pytest

    from insightxpert_api.routes.connections import _build_typed_config

    cfg = _build_typed_config(
        "oracle",
        {"host": "h", "service_name": "S", "username": "u", "password": "p"},
    )
    assert cfg.port == 1521
    with _pytest.raises(Exception, match="invalid oracle config"):
        _build_typed_config("oracle", {"host": "h"})


def test_validate_oracle_selection_rejects_unknown_and_blob():
    from insightxpert_api.connections.oracle_connector import TableDetails
    from insightxpert_api.routes.connections import _validate_oracle_selection

    details = [
        TableDetails(name="EMP", row_count=1, column_count=2, unsupported_columns=[]),
        TableDetails(
            name="DOCS", row_count=1, column_count=2,
            unsupported_columns=["PAYLOAD: BLOB"],
        ),
    ]

    class _FakeOC:
        def __init__(self, cfg):
            pass

        def discovery_details(self):
            return details

        def dispose(self):
            pass

    with patch(
        "insightxpert_api.connections.oracle_connector.OracleConnector", _FakeOC
    ):
        cfg = _oracle_config()
        out = _validate_oracle_selection(cfg, ["EMP"])
        assert out.selected_tables == ["EMP"]
        out_all = _validate_oracle_selection(cfg, None)
        assert out_all.selected_tables is None
        with pytest.raises(Exception, match="unknown tables"):
            _validate_oracle_selection(cfg, ["NOPE"])
        with pytest.raises(Exception, match="unsupported column types"):
            _validate_oracle_selection(cfg, ["DOCS"])


def test_validate_oracle_selection_refuses_system_schema():
    from insightxpert_api.routes.connections import _validate_oracle_selection

    with pytest.raises(Exception, match="system schema"):
        _validate_oracle_selection(_oracle_config(schema="SYSTEM"), ["T"])
