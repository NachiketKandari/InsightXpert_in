"""Phase 1.2 — Alembic 20260425_0001 extends query_metrics cleanly."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, select, text


def test_migration_adds_cost_columns_and_backfills(tmp_path, monkeypatch) -> None:
    db = tmp_path / "mig.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)

    api_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)

    # Upgrade to the revision BEFORE our new one, seed a chat row with the
    # old column shape, then upgrade head and assert back-fill.
    command.upgrade(cfg, "20260424_0001")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO query_metrics "
                "(id, user_id, conversation_id, question, created_at) "
                "VALUES (:id, :u, :c, :q, :t)"
            ),
            {"id": "legacy1", "u": "u1", "c": "c1", "q": "old row", "t": 100},
        )

    # Now apply head — includes 20260425_0001.
    command.upgrade(cfg, "head")

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT source, provider, pricing_version, model, cost_usd "
                "FROM query_metrics WHERE id='legacy1'"
            )
        ).fetchone()

    assert row is not None
    assert row[0] == "chat"
    assert row[1] == "gemini"
    assert row[2] == "legacy"
    assert row[3] is None  # model not recoverable
    assert row[4] is None  # cost not backfilled (model unknown)

    # New columns accept inserts.
    from insightxpert_api.metrics.table import query_metrics

    with engine.begin() as conn:
        conn.execute(
            insert(query_metrics).values(
                id="new1",
                user_id="u2",
                conversation_id="c2",
                question="new",
                created_at=200,
                source="profile",
                provider="gemini",
                model="gemini-2.5-flash",
                cost_usd=0.01,
                pricing_version="2026-04-24-v1",
                source_ref_id="db-x",
            )
        )
        fetched = conn.execute(
            select(query_metrics).where(query_metrics.c.id == "new1")
        ).fetchone()
    assert fetched is not None
    assert fetched._mapping["source"] == "profile"
    assert fetched._mapping["source_ref_id"] == "db-x"
