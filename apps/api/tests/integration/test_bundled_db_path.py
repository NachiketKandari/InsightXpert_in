"""Tests for Phase 1.3 bundled-DB path migration.

Verifies that:
1. ``_list_bundled`` reads from ``Databases/_shared/`` (primary path).
2. A DB present only at the old flat ``Databases/{id}.sqlite`` location is
   still found via the fallback shim (dual-read compatibility).
3. When the same db_id exists in both locations, the ``_shared/`` entry wins.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from insightxpert_api.services.database_service import DatabaseService


def _make_sqlite(path: Path) -> None:
    """Write a minimal valid SQLite file to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()


@pytest.fixture()
def fake_store() -> MagicMock:
    store = MagicMock()
    store.list.return_value = []
    return store


class TestListBundledSharedDir:
    """Primary path: files under _shared/ are discovered."""

    def test_reads_from_shared_subdir(self, tmp_path: Path, fake_store: MagicMock) -> None:
        shared = tmp_path / "_shared"
        _make_sqlite(shared / "alpha.sqlite")
        _make_sqlite(shared / "beta.sqlite")

        svc = DatabaseService(bundled_dir=str(tmp_path), store=fake_store)
        refs = svc._list_bundled()

        db_ids = [r.db_id for r in refs]
        assert "alpha" in db_ids
        assert "beta" in db_ids
        assert all(r.source == "bundled" for r in refs)

    def test_shared_path_is_resolved(self, tmp_path: Path, fake_store: MagicMock) -> None:
        shared = tmp_path / "_shared"
        _make_sqlite(shared / "gamma.sqlite")

        svc = DatabaseService(bundled_dir=str(tmp_path), store=fake_store)
        refs = svc._list_bundled()

        assert len(refs) == 1
        assert refs[0].local_path == str((shared / "gamma.sqlite").resolve())


class TestListBundledFlatFallback:
    """Compat shim: flat Databases/*.sqlite still works (pre-1.3 dev setups)."""

    def test_flat_file_found_when_no_shared_dir(
        self, tmp_path: Path, fake_store: MagicMock
    ) -> None:
        _make_sqlite(tmp_path / "legacy.sqlite")

        svc = DatabaseService(bundled_dir=str(tmp_path), store=fake_store)
        refs = svc._list_bundled()

        db_ids = [r.db_id for r in refs]
        assert "legacy" in db_ids

    def test_flat_file_logs_info(
        self, tmp_path: Path, fake_store: MagicMock
    ) -> None:
        """Fallback to flat layout emits an info-level log mentioning the db_id."""
        from unittest.mock import patch

        import insightxpert_api.services.database_service as _mod

        _make_sqlite(tmp_path / "old_style.sqlite")
        svc = DatabaseService(bundled_dir=str(tmp_path), store=fake_store)

        with patch.object(_mod._log, "info") as mock_info:
            svc._list_bundled()

        assert mock_info.called, "Expected _log.info to be called for the flat-fallback"
        # The first positional arg to info() is the event/message.
        call_args = mock_info.call_args
        event = call_args[0][0] if call_args[0] else call_args[1].get("event", "")
        assert "old_style" in str(call_args) or "fallback" in str(event), (
            f"Expected log to reference db_id or fallback; got {call_args}"
        )

    def test_shared_wins_over_flat_for_same_db_id(
        self, tmp_path: Path, fake_store: MagicMock
    ) -> None:
        """When same db_id exists in both locations, _shared/ takes precedence."""
        shared = tmp_path / "_shared"
        _make_sqlite(shared / "dup.sqlite")
        _make_sqlite(tmp_path / "dup.sqlite")  # old flat copy

        svc = DatabaseService(bundled_dir=str(tmp_path), store=fake_store)
        refs = svc._list_bundled()

        # Only one entry for "dup".
        dup_refs = [r for r in refs if r.db_id == "dup"]
        assert len(dup_refs) == 1
        # The winning path must be under _shared/.
        assert "_shared" in dup_refs[0].local_path


class TestListBundledEdgeCases:
    """Edge cases: missing dir, empty dir."""

    def test_missing_bundled_dir_returns_empty(
        self, tmp_path: Path, fake_store: MagicMock
    ) -> None:
        nonexistent = tmp_path / "no_such_dir"
        svc = DatabaseService(bundled_dir=str(nonexistent), store=fake_store)
        assert svc._list_bundled() == []

    def test_empty_shared_dir_returns_empty(
        self, tmp_path: Path, fake_store: MagicMock
    ) -> None:
        (tmp_path / "_shared").mkdir()
        svc = DatabaseService(bundled_dir=str(tmp_path), store=fake_store)
        assert svc._list_bundled() == []
