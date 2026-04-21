"""Engine smoke — WAL pragma is applied, engine is cached, connections are sqlite."""

from __future__ import annotations

from sqlalchemy import text

from insightxpert_api.db.engine import get_engine, reset_engine_cache


def test_engine_applies_wal_pragma(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/a.db")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()
    reset_engine_cache()

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("PRAGMA journal_mode")).scalar_one()
        assert row.lower() == "wal"


def test_engine_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/b.db")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()
    reset_engine_cache()
    assert get_engine() is get_engine()
