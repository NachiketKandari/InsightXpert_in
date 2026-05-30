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


_TEST_KEY = "GbhRElFcz5W3rC9V8a4GQYoT3p6jZCqZ4EQRQyGzwYY="


def test_list_unions_postgres_rows_from_databases_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", _TEST_KEY)
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()
    from insightxpert_api.connections.encryption import encrypt
    import json

    cfg = {
        "kind": "postgres",
        "host": "h",
        "port": 5432,
        "username": "u",
        "password": "p",
        "database": "d",
    }
    encrypted_cfg = encrypt(json.dumps(cfg))

    svc = _svc_with_stubbed_pg_rows(
        tmp_path,
        [
            {
                "db_id": "toxicology_pg",
                "kind": "postgres",
                "visibility": "public",
                "connection_config_encrypted": encrypted_cfg,
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
    assert pg.connection_url == "postgresql+psycopg://u:p@h:5432/d?sslmode=require"


def test_decrypt_failure_skips_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Listing must not fail hard when decryption fails — just drop the row with a warning."""
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", _TEST_KEY)
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    svc = _svc_with_stubbed_pg_rows(
        tmp_path,
        [
            {
                "db_id": "toxicology_pg",
                "kind": "postgres",
                "visibility": "public",
                "connection_config_encrypted": "invalid-garbage-encrypted-string",
            }
        ],
    )

    refs = svc.list(session_id="s1")
    db_ids = {r.db_id for r in refs}
    assert "toxicology_pg" not in db_ids
