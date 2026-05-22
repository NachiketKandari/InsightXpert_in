import sqlite3
from pathlib import Path

import pytest

from insightxpert_api.db.connector import DatabaseConnector, ForbiddenSQLError
from insightxpert_api.services.database_service import DatabaseRef


@pytest.fixture
def tiny_db(tmp_path: Path) -> Path:
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1);")
    con.close()
    return p


def test_connector_executes_via_sqlite_adapter(tiny_db: Path):
    ref = DatabaseRef(db_id="t", source="bundled", local_path=str(tiny_db))
    connector = DatabaseConnector(ref)
    result = connector.execute("SELECT x FROM t")
    assert result.rows == [[1]]
    assert result.columns == ["x"]


def test_connector_blocks_writes(tiny_db: Path):
    ref = DatabaseRef(db_id="t", source="bundled", local_path=str(tiny_db))
    connector = DatabaseConnector(ref)
    with pytest.raises(ForbiddenSQLError):
        connector.execute("INSERT INTO t VALUES (2)")
