"""Migration smoke — B3 creates audit_log, query_metrics, databases, database_shares."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _alembic_config(db_path: Path) -> Config:
    api_dir = Path(__file__).resolve().parents[2]  # apps/api
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_upgrade_creates_audit_log(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    command.upgrade(_alembic_config(db), "head")
    insp = inspect(create_engine(f"sqlite:///{db}"))
    cols = {c["name"] for c in insp.get_columns("audit_log")}
    assert cols == {
        "id", "user_id", "method", "path", "resource_type", "resource_id",
        "status_code", "ip", "user_agent", "created_at",
    }
    idx = {i["name"] for i in insp.get_indexes("audit_log")}
    assert "ix_audit_log_created_at" in idx
    assert "ix_audit_log_user_id_created_at" in idx


def test_upgrade_creates_query_metrics(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    command.upgrade(_alembic_config(db), "head")
    insp = inspect(create_engine(f"sqlite:///{db}"))
    cols = {c["name"] for c in insp.get_columns("query_metrics")}
    # B3 core columns must all still be present; Phase 1.2 adds 6 more
    # (see 20260425_0001 — source/provider/model/cost_usd/pricing_version/
    # source_ref_id). Assert superset semantics so future migrations don't
    # break this test on every column add.
    b3_core = {
        "id", "user_id", "conversation_id", "db_id", "question", "final_sql",
        "agent_mode", "tokens_in", "tokens_out", "duration_ms", "thumbs",
        "stage_timings_json", "agent_trace_summary_json", "created_at",
    }
    phase_1_2 = {
        "source", "provider", "model", "cost_usd",
        "pricing_version", "source_ref_id",
    }
    assert b3_core.issubset(cols)
    assert phase_1_2.issubset(cols)
    idx = {i["name"] for i in insp.get_indexes("query_metrics")}
    assert "ix_query_metrics_created_at" in idx
    assert "ix_query_metrics_user_id_created_at" in idx
    assert "ix_query_metrics_db_id" in idx
    # Phase 1.2 — index for "profile spend by user last 24h".
    assert "ix_query_metrics_source_created_at" in idx


def test_upgrade_creates_databases_and_shares(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    command.upgrade(_alembic_config(db), "head")
    insp = inspect(create_engine(f"sqlite:///{db}"))
    db_cols = {c["name"] for c in insp.get_columns("databases")}
    assert db_cols == {
        "db_id", "owner_user_id", "visibility", "size_bytes", "created_at",
        # Added by 20260424_0001 (Tier-1 full-schema mode).
        "pipeline_mode_default",
        # Added by 20260425_0002 (postgres dialect adapter).
        "dialect", "connection_url_env_var",
        # Added by 20260427_0001 (BYO external DB connector).
        "kind", "connection_config_encrypted",
    }
    share_cols = {c["name"] for c in insp.get_columns("database_shares")}
    assert share_cols == {"db_id", "user_id", "created_at"}


def test_upgrade_seeds_bundled_bird_dbs(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from insightxpert_api.config import get_settings
    get_settings.cache_clear()

    command.upgrade(_alembic_config(db), "head")
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT db_id, owner_user_id, visibility FROM databases "
            "ORDER BY db_id"
        )).fetchall()
    # Seeding is best-effort (only runs if apps/api/Databases exists). When it
    # does run, every seeded row must be visibility='public' with NULL owner.
    for row in rows:
        assert row.visibility == "public"
        assert row.owner_user_id is None
    # At least one seeded DB should exist in our dev tree; skip that assertion
    # in environments where Databases/ isn't present.
    api_dir = Path(__file__).resolve().parents[2]
    if (api_dir / "Databases").exists():
        assert len(rows) >= 1
        names = {r.db_id for r in rows}
        # Plan-specified three should be present.
        assert "california_schools" in names
