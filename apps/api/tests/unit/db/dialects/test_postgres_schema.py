"""Postgres schema extractor — mocked-connection unit tests."""
from unittest.mock import MagicMock

from insightxpert_api.db.dialects.postgres_schema import extract_postgres_schema
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema


def _mocked_conn(fetchall_sequence: list[list]) -> MagicMock:
    """Build a mock psycopg connection whose cursor.fetchall returns the given
    sequence of results in order (one per execute call)."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.side_effect = fetchall_sequence
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


def test_extract_empty_schema():
    # only one execute (tables list) — returns empty
    conn = _mocked_conn([[]])
    schema = extract_postgres_schema(conn, schema_name="toxicology")
    assert isinstance(schema, DatabaseSchema)
    assert schema.tables == []


def test_extract_one_table_with_cols_pk_and_fk():
    conn = _mocked_conn([
        [("molecule",)],                                      # tables
        [("id", "integer", "NO", None),                       # columns
         ("label", "text", "YES", None)],
        [("id",)],                                            # PKs (from _fetch_pk)
        [("molecule_atom_id_fkey", "molecule", "atom_id",     # fks — but molecule has no atom_id, keep test shape
          "atom", "id")],
    ])
    schema = extract_postgres_schema(conn, schema_name="toxicology")
    assert len(schema.tables) == 1
    t = schema.tables[0]
    assert t.name == "molecule"
    assert {c.name for c in t.columns} == {"id", "label"}
    id_col = next(c for c in t.columns if c.name == "id")
    assert id_col.primary_key is True
    assert id_col.nullable is False
    label_col = next(c for c in t.columns if c.name == "label")
    assert label_col.primary_key is False
    assert label_col.nullable is True
    assert len(t.foreign_keys) == 1
    assert t.foreign_keys[0].column == "atom_id"
    assert t.foreign_keys[0].ref_table == "atom"
    assert t.foreign_keys[0].ref_column == "id"
