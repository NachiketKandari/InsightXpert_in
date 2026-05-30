"""Tests for DATABASE_URL config and connection-pool settings.

Verifies:
1. Default DATABASE_URL is sqlite.
2. Env-var override is picked up correctly.
3. Pool kwargs are present on Settings for non-sqlite URLs and have correct defaults.
"""

from __future__ import annotations

from insightxpert_api.config import Settings


def _make_settings(**overrides: str) -> Settings:
    """Construct a Settings object with test-minimum required fields."""
    base = {
        "SESSION_SECRET": "x" * 32,
        "GEMINI_API_KEY": "test-key",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def test_default_database_url_is_sqlite():
    """Out-of-the-box DATABASE_URL must point at the local sqlite file."""
    s = _make_settings()
    assert s.database_url.startswith("sqlite:///")


def test_database_url_env_override(monkeypatch):
    """DATABASE_URL env var overrides the default sqlite path."""
    pg_url = "postgresql+psycopg://postgres:secret@localhost:5432/insightxpert"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    s = _make_settings()
    assert s.database_url == pg_url


def test_pool_kwargs_present_for_non_sqlite_url(monkeypatch):
    """Pool settings exist on Settings and carry the expected defaults."""
    pg_url = "postgresql+psycopg://postgres:secret@localhost:5432/insightxpert"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    s = _make_settings()
    # These fields must exist and be non-zero so get_engine() can forward them.
    assert s.db_pool_size == 15
    assert s.db_max_overflow == 10
    assert s.db_pool_timeout == 10
    assert s.db_pool_pre_ping is False
