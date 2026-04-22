"""DatabaseService — Postgres rows from the `databases` table."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from insightxpert_api.services.database_service import DatabaseService


def _svc_with_stubbed_pg_rows(tmp_path: Path, rows: list[dict]) -> DatabaseService:
    """Build a DatabaseService with a controlled set of non-sqlite rows."""
    shared = tmp_path / "_shared"
    shared.mkdir(exist_ok=True)
    store = MagicMock()
    store.list.return_value = []
    svc = DatabaseService(bundled_dir=str(tmp_path), store=store)
    svc._fetch_non_sqlite_rows = lambda: rows  # type: ignore[assignment]
    return svc


def test_list_unions_postgres_rows_from_databases_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DATABASE_URL_TOXICOLOGY_PG", "postgresql://u:p@h:5432/d")

    svc = _svc_with_stubbed_pg_rows(
        tmp_path,
        [
            {
                "db_id": "toxicology_pg",
                "visibility": "public",
                "connection_url_env_var": "DATABASE_URL_TOXICOLOGY_PG",
                "dialect": "postgres",
            }
        ],
    )
    (tmp_path / "_shared" / "toxicology.sqlite").write_bytes(b"stub")

    refs = svc.list(session_id="s1")
    by_id = {r.db_id: r for r in refs}
    assert "toxicology" in by_id
    assert "toxicology_pg" in by_id

    pg = by_id["toxicology_pg"]
    assert pg.dialect == "postgres"
    assert pg.local_path is None
    assert pg.connection_url == "postgresql://u:p@h:5432/d"
    assert pg.connection_url_env_var == "DATABASE_URL_TOXICOLOGY_PG"


def test_missing_env_var_skips_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Listing must not fail hard when an env var is unset — just drop the row
    with a warning. Hard-fail on use is the operator's cue."""
    monkeypatch.delenv("DATABASE_URL_TOXICOLOGY_PG", raising=False)
    svc = _svc_with_stubbed_pg_rows(
        tmp_path,
        [
            {
                "db_id": "toxicology_pg",
                "visibility": "public",
                "connection_url_env_var": "DATABASE_URL_TOXICOLOGY_PG",
                "dialect": "postgres",
            }
        ],
    )

    refs = svc.list(session_id="s1")
    db_ids = {r.db_id for r in refs}
    assert "toxicology_pg" not in db_ids
