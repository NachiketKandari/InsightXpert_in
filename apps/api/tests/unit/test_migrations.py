"""Migration smoke — upgrade head creates the users table with expected columns."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _alembic_config(db_path: Path) -> Config:
    api_dir = Path(__file__).resolve().parents[2]  # apps/api
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_upgrade_creates_users_table(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    command.upgrade(_alembic_config(db), "head")
    insp = inspect(create_engine(f"sqlite:///{db}"))
    cols = {c["name"] for c in insp.get_columns("users")}
    assert cols == {
        "id", "email", "password_hash", "role", "is_active",
        "must_change_password", "sessions_valid_after",
        "created_at", "updated_at", "last_seen_at",
    }
