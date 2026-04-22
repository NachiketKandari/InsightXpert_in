"""Unit tests for the SQLite → Postgres converter.

Runs against an in-memory SQLite source. The Postgres target is mocked via
psycopg — we verify the DDL + COPY statements produced, not that they actually
execute on a real Postgres server. E2E correctness is in tests/integration/test_postgres_e2e.py.
"""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def tiny_sqlite(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.sqlite"
    con = sqlite3.connect(p)
    con.executescript(
        """
        CREATE TABLE atom (id INTEGER PRIMARY KEY, element TEXT NOT NULL);
        CREATE TABLE bond (
            id INTEGER PRIMARY KEY,
            atom1 INTEGER REFERENCES atom(id),
            atom2 INTEGER REFERENCES atom(id)
        );
        INSERT INTO atom VALUES (1, 'H'), (2, 'C');
        INSERT INTO bond VALUES (1, 1, 2);
        """
    )
    con.close()
    return p


def test_converter_creates_schema_and_ports_tables(tiny_sqlite: Path):
    from insightxpert_api.scripts.sqlite_to_postgres import convert

    # Build a mocked psycopg connection. Since convert() counts rows at the
    # end via dst.cursor().fetchone(), we need to return (N,) for those.
    pg_cur = MagicMock()
    # First two fetchone calls are the post-COPY row-count checks (atom=2, bond=1)
    pg_cur.fetchone.side_effect = [(2,), (1,)]

    pg_conn = MagicMock()
    pg_conn.cursor.return_value.__enter__.return_value = pg_cur

    with patch("insightxpert_api.scripts.sqlite_to_postgres.psycopg") as pg:
        pg.connect.return_value.__enter__.return_value = pg_conn

        convert(
            sqlite_path=tiny_sqlite,
            pg_url="postgresql://u:p@h:5432/d",
            pg_schema="tox_test",
            drop_existing=True,
        )

    # Collect all SQL that was executed. psycopg.sql.SQL objects are not plain
    # strings, so convert to str() for substring matching.
    executed = []
    for call in pg_cur.execute.call_args_list:
        if call.args:
            executed.append(str(call.args[0]))
    combined = " ".join(executed)

    assert "DROP SCHEMA" in combined
    assert "CREATE SCHEMA" in combined
    assert "CREATE TABLE" in combined
    # Two tables were created
    assert combined.count("CREATE TABLE") == 2
    # FK was added after table creation
    assert "FOREIGN KEY" in combined or "ADD FOREIGN KEY" in combined
    # COPY used for bulk row insertion (one per table)
    assert pg_cur.copy.call_count == 2
