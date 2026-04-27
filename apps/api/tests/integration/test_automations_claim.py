"""Multi-replica claim safety: claim_due_automations must atomically advance
``next_run_at`` so a second concurrent claim cannot pick up the same rows.

Postgres (``FOR UPDATE SKIP LOCKED``) is exercised in production. Tests here
hit SQLite, which uses the read-then-update fallback. The contract is the
same: after claim, the rows no longer match the due predicate.
"""
from __future__ import annotations

from sqlalchemy import insert, text, update

from insightxpert_api.automations import repository as repo
from insightxpert_api.automations.table import automations
from insightxpert_api.db.engine import get_engine


def _seed(*, n: int, due_at: int) -> None:
    rows = [
        {
            "id": f"auto-{i}",
            "owner_user_id": "u1",
            "db_id": "db1",
            "name": f"a{i}",
            "nl_query": "q",
            "sql_queries_json": "[]",
            "cron_expression": "*/5 * * * *",
            "is_active": True,
            "next_run_at": due_at,
            "created_at": due_at - 60,
            "updated_at": due_at - 60,
        }
        for i in range(n)
    ]
    engine = get_engine()
    with engine.begin() as conn:
        # FKs reference users/databases; this test is isolated and only
        # exercises the claim mechanism, so drop FK enforcement for the
        # seeding insert.
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = OFF"))
        for r in rows:
            conn.execute(insert(automations).values(**r))


def test_claim_advances_next_run_at(fresh_db):
    now = 1_700_000_000
    _seed(n=3, due_at=now - 1)
    claimed = repo.claim_due_automations(now_ts=now, batch_size=10)
    assert len(claimed) == 3
    # After claim, list_due should be empty for this tick — claim parked
    # next_run_at at now+1.
    assert repo.list_due_automations(now_ts=now) == []


def test_claim_respects_batch_size(fresh_db):
    now = 1_700_000_000
    _seed(n=5, due_at=now - 1)
    first = repo.claim_due_automations(now_ts=now, batch_size=2)
    assert len(first) == 2
    rest = repo.claim_due_automations(now_ts=now, batch_size=10)
    assert len(rest) == 3


def test_claim_skips_inactive(fresh_db):
    now = 1_700_000_000
    _seed(n=2, due_at=now - 1)
    with get_engine().begin() as conn:
        conn.execute(
            update(automations)
            .where(automations.c.id == "auto-0")
            .values(is_active=False)
        )
    claimed = repo.claim_due_automations(now_ts=now, batch_size=10)
    assert {r["id"] for r in claimed} == {"auto-1"}
