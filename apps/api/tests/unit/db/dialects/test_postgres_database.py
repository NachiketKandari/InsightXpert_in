from unittest.mock import MagicMock, patch

import pytest

from insightxpert_api.db.dialects.postgres_database import PostgresDatabase


def test_postgres_database_wraps_psycopg():
    ref = MagicMock()
    ref.db_id = "toxicology_pg"
    ref.connection_url = "postgresql://u:p@h:5432/d"

    with patch("insightxpert_api.db.dialects.postgres_database.psycopg") as pg:
        cur = MagicMock()
        cur.description = [("c1",)]
        cur.fetchall.return_value = [(1,), (2,)]
        pg.connect.return_value.cursor.return_value.__enter__.return_value = cur

        db = PostgresDatabase(ref)
        rows = db.execute("SELECT 1")
        assert rows == [(1,), (2,)]
        db.close()

        pg.connect.assert_called_once()
        kwargs = pg.connect.call_args.kwargs
        assert "default_transaction_read_only=on" in kwargs["options"]


def test_postgres_database_raises_without_url():
    ref = MagicMock()
    ref.db_id = "toxicology_pg"
    ref.connection_url = None
    with pytest.raises(ValueError, match="missing connection_url"):
        PostgresDatabase(ref)
