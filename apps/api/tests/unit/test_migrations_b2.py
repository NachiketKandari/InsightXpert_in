"""B2 migration smoke — upgrade head creates the orchestration tables."""

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


def test_upgrade_creates_orchestration_tables(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from insightxpert_api.config import get_settings

    get_settings.cache_clear()

    command.upgrade(_alembic_config(db), "head")
    insp = inspect(create_engine(f"sqlite:///{db}"))

    existing = set(insp.get_table_names())
    expected = {
        "conversations",
        "messages",
        "prompt_templates",
        "insights",
        "agent_executions",
        "enrichment_traces",
    }
    assert expected.issubset(existing), f"missing tables: {expected - existing}"

    conv_cols = {c["name"] for c in insp.get_columns("conversations")}
    conv_expected = {
        "id", "user_id", "db_id", "title", "is_starred", "created_at", "updated_at",
    }
    assert conv_expected.issubset(conv_cols), f"missing conversations columns: {conv_expected - conv_cols}"

    msg_cols = {c["name"] for c in insp.get_columns("messages")}
    msg_expected = {
        "id", "conversation_id", "role", "content", "chunks_json",
        "tokens_in", "tokens_out", "created_at",
    }
    assert msg_expected.issubset(msg_cols), f"missing messages columns: {msg_expected - msg_cols}"

    at_cols = {c["name"] for c in insp.get_columns("agent_executions")}
    assert "task_id" in at_cols and "steps_json" in at_cols and "duration_ms" in at_cols

    et_cols = {c["name"] for c in insp.get_columns("enrichment_traces")}
    assert "source_index" in et_cols and "rationale" in et_cols


def test_orchestration_tables_register_on_shared_metadata():
    """The Alembic env.py imports the orch table module; autogen sees them.

    We verify by importing the shared metadata and confirming every
    orchestration table is registered.
    """
    from insightxpert_api.db.base import metadata
    from insightxpert_api.orchestration import table as _orch  # noqa: F401

    table_names = set(metadata.tables.keys())
    for t in ("conversations", "messages", "prompt_templates",
              "insights", "agent_executions", "enrichment_traces"):
        assert t in table_names, f"{t} not registered on shared metadata"
