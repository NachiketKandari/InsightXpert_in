import sqlite3
from pathlib import Path

from insightxpert_api.services.database_service import DatabaseService
from insightxpert_api.storage.local import LocalStorage

BUNDLED_DIR = Path(__file__).resolve().parents[2] / "Databases"


def _make_sqlite(path: Path) -> bytes:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INT)")
    con.commit()
    con.close()
    return path.read_bytes()


def test_lists_bundled_dbs(tmp_path):
    svc = DatabaseService(bundled_dir=str(BUNDLED_DIR), store=LocalStorage(str(tmp_path)))
    refs = svc.list(session_id="s1")
    ids = {r.db_id for r in refs if r.source == "bundled"}
    assert "california_schools" in ids
    assert "financial" in ids


def test_resolves_bundled_by_id(tmp_path):
    svc = DatabaseService(bundled_dir=str(BUNDLED_DIR), store=LocalStorage(str(tmp_path)))
    ref = svc.resolve("s1", "california_schools")
    assert ref is not None
    assert ref.source == "bundled"
    assert ref.local_path.endswith("california_schools.sqlite")


def test_resolve_missing_returns_none(tmp_path):
    svc = DatabaseService(bundled_dir=str(BUNDLED_DIR), store=LocalStorage(str(tmp_path)))
    assert svc.resolve("s1", "doesnotexist") is None


def test_upload_roundtrip(tmp_path):
    svc = DatabaseService(bundled_dir=str(BUNDLED_DIR), store=LocalStorage(str(tmp_path)))
    raw = _make_sqlite(tmp_path / "seed.sqlite")
    ref = svc.save_upload(session_id="s1", db_id="mydb", data=raw)
    assert ref.source == "uploaded"
    assert ref.db_id == "mydb"
    # Can open via sqlite3 via the returned local_path
    con = sqlite3.connect(ref.local_path)
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    con.close()
    assert ("t",) in tables


def test_uploaded_appears_in_list_and_is_isolated_per_session(tmp_path):
    svc = DatabaseService(bundled_dir=str(BUNDLED_DIR), store=LocalStorage(str(tmp_path)))
    raw = _make_sqlite(tmp_path / "seed.sqlite")
    svc.save_upload(session_id="s1", db_id="mydb", data=raw)
    s1_ids = {r.db_id for r in svc.list("s1")}
    s2_ids = {r.db_id for r in svc.list("s2")}
    assert "mydb" in s1_ids
    assert "mydb" not in s2_ids
