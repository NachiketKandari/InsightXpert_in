import sqlite3

import pytest

from insightxpert_api.db import DatabaseConnector, ForbiddenSQLError, ddl


@pytest.fixture
def tiny_db(tmp_path):
    p = tmp_path / "t.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE x (id INTEGER, name TEXT)")
    con.execute("INSERT INTO x VALUES (1,'a'),(2,'b')")
    con.commit()
    con.close()
    return str(p)


def test_read_returns_rows(tiny_db):
    c = DatabaseConnector(tiny_db)
    result = c.execute("SELECT id, name FROM x ORDER BY id")
    assert result.columns == ["id", "name"]
    assert result.rows == [[1, "a"], [2, "b"]]
    assert result.execution_time_ms >= 0


def test_write_is_blocked(tiny_db):
    c = DatabaseConnector(tiny_db)
    with pytest.raises(ForbiddenSQLError):
        c.execute("INSERT INTO x VALUES (3,'c')")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE x SET name='z' WHERE id=1",
        "DELETE FROM x",
        "DROP TABLE x",
        "ALTER TABLE x ADD COLUMN y INT",
        "CREATE TABLE y (id INT)",
        "TRUNCATE TABLE x",
        "PRAGMA journal_mode = WAL",
    ],
)
def test_all_write_variants_blocked(tiny_db, sql):
    c = DatabaseConnector(tiny_db)
    with pytest.raises(ForbiddenSQLError):
        c.execute(sql)


def test_row_limit_applies(tiny_db):
    c = DatabaseConnector(tiny_db, row_limit=1)
    result = c.execute("SELECT * FROM x")
    assert len(result.rows) == 1


def test_ddl_returns_create_statements(tiny_db):
    schema = ddl(tiny_db)
    assert "CREATE TABLE" in schema.upper()
    assert "x" in schema
