import sqlite3
from pathlib import Path

import pytest

from insightxpert_api.db.dialects import get_adapter
from insightxpert_api.db.dialects.base import DialectAdapter, ProfilingQueryPack


@pytest.fixture
def tiny_sqlite(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.sqlite"
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT); "
        "INSERT INTO t VALUES (1, 'a'), (2, 'b');"
    )
    con.close()
    return p


def test_sqlite_adapter_registered():
    adapter = get_adapter("sqlite")
    assert isinstance(adapter, DialectAdapter)
    assert adapter.name == "sqlite"
    assert adapter.sqlglot_dialect == "sqlite"
    assert adapter.prompt_variant == "sqlite"


def test_sqlite_forbidden_regex_blocks_writes():
    adapter = get_adapter("sqlite")
    assert adapter.forbidden_sql_re.search("INSERT INTO t VALUES (3)")
    assert adapter.forbidden_sql_re.search("PRAGMA journal_mode = WAL")
    assert adapter.forbidden_sql_re.search("ATTACH 'x.db' AS x")
    assert not adapter.forbidden_sql_re.search("SELECT * FROM t")


def test_sqlite_profiling_queries_shape():
    adapter = get_adapter("sqlite")
    pack = adapter.profiling_queries()
    assert isinstance(pack, ProfilingQueryPack)
    assert "{table}" in pack.null_count
    assert "{col}" in pack.null_count
