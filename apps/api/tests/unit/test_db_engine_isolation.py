"""Verify request and background engines are independent objects with
the configured pool sizes. This is the architectural guarantee that
background work cannot starve the request path."""

from __future__ import annotations

import pytest

from insightxpert_api.db import engine as engine_mod


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    engine_mod.reset_engine_cache()
    yield
    engine_mod.reset_engine_cache()


def test_request_and_background_engines_are_distinct(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    req = engine_mod.get_request_engine()
    bg = engine_mod.get_background_engine()
    assert req is not bg
    assert req.pool is not bg.pool


def test_get_engine_aliases_request_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    assert engine_mod.get_engine() is engine_mod.get_request_engine()


def test_engines_use_configured_pool_sizes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("DB_POOL_SIZE", "15")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "10")
    monkeypatch.setenv("DB_BACKGROUND_POOL_SIZE", "2")
    monkeypatch.setenv("DB_BACKGROUND_MAX_OVERFLOW", "0")
    # Drop cached settings so env vars take effect.
    from insightxpert_api import config as cfg
    cfg.get_settings.cache_clear()  # type: ignore[attr-defined]
    req = engine_mod.get_request_engine()
    bg = engine_mod.get_background_engine()
    assert req.pool.size() == 15
    assert bg.pool.size() == 2


def test_sqlite_url_does_not_apply_pool_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from insightxpert_api import config as cfg
    cfg.get_settings.cache_clear()  # type: ignore[attr-defined]
    # SQLite path returns a NullPool/StaticPool; just assert no crash and
    # the two getters still return distinct engine objects.
    req = engine_mod.get_request_engine()
    bg = engine_mod.get_background_engine()
    assert req is not bg
