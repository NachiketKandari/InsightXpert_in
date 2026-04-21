"""Migration smoke — Phase C1 creates 5 automations tables with correct shape.

Asserts column sets, nullable flags on the C2-reserved column, indices, and
that CHECK constraints accept valid enum values and reject invalid ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def _alembic_config(db_path: Path) -> Config:
    api_dir = Path(__file__).resolve().parents[2]  # apps/api
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


@pytest.fixture
def engine(tmp_path, monkeypatch):
    db = tmp_path / "c1.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    from insightxpert_api.config import get_settings

    get_settings.cache_clear()
    command.upgrade(_alembic_config(db), "head")
    eng = create_engine(f"sqlite:///{db}")
    # Enable FK enforcement for this fixture so ON DELETE CASCADE behavior is real.
    with eng.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
    return eng


def test_all_five_tables_exist(engine):
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for t in (
        "automations",
        "automation_triggers",
        "automation_runs",
        "trigger_templates",
        "notifications",
    ):
        assert t in tables


def test_automations_columns(engine):
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("automations")}
    assert set(cols) == {
        "id",
        "name",
        "description",
        "nl_query",
        "sql_queries_json",
        "db_id",
        "cron_expression",
        "is_active",
        "owner_user_id",
        "source_conversation_id",
        "source_message_id",
        "workflow_graph_json",
        "last_run_at",
        "next_run_at",
        "created_at",
        "updated_at",
    }
    # Phase C2 reservation must allow NULL.
    assert cols["workflow_graph_json"]["nullable"] is True
    # No org_id column — single-tenant.
    assert "org_id" not in cols


def test_automations_indices(engine):
    insp = inspect(engine)
    idx = {i["name"] for i in insp.get_indexes("automations")}
    assert {"ix_auto_owner_active", "ix_auto_next_run", "ix_auto_db_id"} <= idx


def test_triggers_columns(engine):
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("automation_triggers")}
    assert cols == {
        "id",
        "automation_id",
        "ordinal",
        "type",
        "column",
        "operator",
        "value",
        "change_percent",
        "scope",
        "nl_text",
    }
    # Slope is deliberately absent.
    assert "slope_window" not in cols


def test_runs_columns(engine):
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("automation_runs")}
    assert cols == {
        "id",
        "automation_id",
        "status",
        "result_json",
        "row_count",
        "execution_time_ms",
        "triggers_fired_json",
        "error_message",
        "created_at",
    }


def test_templates_columns(engine):
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("trigger_templates")}
    assert cols == {
        "id",
        "name",
        "description",
        "conditions_json",
        "owner_user_id",
        "created_at",
        "updated_at",
    }


def test_notifications_columns(engine):
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("notifications")}
    assert cols == {
        "id",
        "user_id",
        "automation_id",
        "run_id",
        "title",
        "message",
        "severity",
        "is_read",
        "created_at",
    }
    idx = {i["name"] for i in insp.get_indexes("notifications")}
    assert "ix_notif_user_unread_ts" in idx


def _seed_user(conn, user_id: str = "u1") -> None:
    """Insert a minimal users row so FK-constrained inserts succeed."""
    conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, "
            "must_change_password, sessions_valid_after, created_at, updated_at) "
            "VALUES (:id, :email, 'x', 'user', 0, 0, 0, 0)"
        ),
        {"id": user_id, "email": f"{user_id}@test"},
    )


def test_trigger_type_check_constraint(engine):
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        _seed_user(conn)
        conn.execute(
            text(
                "INSERT INTO automations (id, name, nl_query, sql_queries_json, "
                "db_id, cron_expression, is_active, owner_user_id, created_at, updated_at) "
                "VALUES ('a1', 'x', 'q', '[]', 'toxicology', '* * * * *', 1, 'u1', 0, 0)"
            )
        )
        # Valid type accepted.
        conn.execute(
            text(
                "INSERT INTO automation_triggers (id, automation_id, ordinal, type) "
                "VALUES ('t1', 'a1', 0, 'threshold')"
            )
        )
    # Invalid type rejected.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.execute(
                text(
                    "INSERT INTO automation_triggers (id, automation_id, ordinal, type) "
                    "VALUES ('t2', 'a1', 1, 'slope')"
                )
            )


def test_run_status_check_constraint(engine):
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        _seed_user(conn)
        conn.execute(
            text(
                "INSERT INTO automations (id, name, nl_query, sql_queries_json, "
                "db_id, cron_expression, is_active, owner_user_id, created_at, updated_at) "
                "VALUES ('a1', 'x', 'q', '[]', 'toxicology', '* * * * *', 1, 'u1', 0, 0)"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.execute(
                text(
                    "INSERT INTO automation_runs (id, automation_id, status, created_at) "
                    "VALUES ('r1', 'a1', 'weird', 0)"
                )
            )


def test_notification_severity_check_constraint(engine):
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        _seed_user(conn)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.execute(
                text(
                    "INSERT INTO notifications "
                    "(id, user_id, title, message, severity, is_read, created_at) "
                    "VALUES ('n1', 'u1', 't', 'm', 'critical', 0, 0)"
                )
            )


def test_cascade_delete_automation_drops_triggers_and_runs(engine):
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        _seed_user(conn)
        conn.execute(
            text(
                "INSERT INTO automations (id, name, nl_query, sql_queries_json, "
                "db_id, cron_expression, is_active, owner_user_id, created_at, updated_at) "
                "VALUES ('a1', 'x', 'q', '[]', 'toxicology', '* * * * *', 1, 'u1', 0, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO automation_triggers (id, automation_id, ordinal, type) "
                "VALUES ('t1', 'a1', 0, 'threshold')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO automation_runs (id, automation_id, status, created_at) "
                "VALUES ('r1', 'a1', 'success', 0)"
            )
        )
    # Delete parent
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))
        conn.execute(text("DELETE FROM automations WHERE id = 'a1'"))
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT COUNT(*) FROM automation_triggers")
        ).scalar() == 0
        assert conn.execute(
            text("SELECT COUNT(*) FROM automation_runs")
        ).scalar() == 0
