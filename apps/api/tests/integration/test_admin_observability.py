"""Integration tests for /api/v1/admin/overview, /admin/audit, /admin/metrics."""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import insert

from insightxpert_api.admin import overview_cache
from insightxpert_api.audit.table import audit_log
from insightxpert_api.db.engine import get_engine
from insightxpert_api.metrics.table import query_metrics


@pytest.fixture(autouse=True)
def _clear_overview_cache():
    overview_cache.clear()
    yield
    overview_cache.clear()


def _insert_metric(**kw) -> None:
    defaults = dict(
        id=str(uuid.uuid4()),
        user_id="u",
        conversation_id="c",
        db_id="california_schools",
        question="?",
        final_sql=None,
        agent_mode="basic",
        tokens_in=10,
        tokens_out=20,
        duration_ms=100,
        thumbs=None,
        stage_timings_json=None,
        agent_trace_summary_json=None,
        created_at=int(time.time()),
    )
    defaults.update(kw)
    with get_engine().begin() as conn:
        conn.execute(insert(query_metrics).values(**defaults))


def _insert_audit(**kw) -> None:
    defaults = dict(
        id=str(uuid.uuid4()),
        user_id=None,
        method="POST",
        path="/x",
        resource_type=None,
        resource_id=None,
        status_code=200,
        ip=None,
        user_agent=None,
        created_at=int(time.time()),
    )
    defaults.update(kw)
    with get_engine().begin() as conn:
        conn.execute(insert(audit_log).values(**defaults))


# ---------------- Forbidden guards ----------------


def test_non_admin_forbidden_everywhere(user_client):
    client, _ = user_client
    assert client.get("/api/v1/admin/overview/").status_code == 403
    assert client.get("/api/v1/admin/audit/").status_code == 403
    assert client.get("/api/v1/admin/metrics/").status_code == 403


# ---------------- Overview ----------------


def test_overview_zero_state(admin_client):
    client, _ = admin_client
    r = client.get("/api/v1/admin/overview/")
    assert r.status_code == 200
    body = r.json()
    assert body["active_users_24h"] == 0
    assert body["chats_today"] == 0
    assert body["tokens_today"] == 0
    assert body["thumbs_ratio_7d"] is None
    assert body["sparkline_7d"] == []
    assert body["total_users"] >= 1  # the admin itself


def test_overview_caches(admin_client, monkeypatch):
    client, _ = admin_client

    calls = {"n": 0}
    real_compute = overview_cache.get_or_compute

    def spy(key, compute):
        def _wrapped():
            calls["n"] += 1
            return compute()
        return real_compute(key, _wrapped)

    monkeypatch.setattr(
        "insightxpert_api.routes.admin_overview.overview_cache.get_or_compute",
        spy,
    )

    r1 = client.get("/api/v1/admin/overview/")
    assert r1.status_code == 200
    r2 = client.get("/api/v1/admin/overview/")
    assert r2.status_code == 200
    # Second call must be served from the cache: the inner compute runs exactly once.
    assert calls["n"] == 1


def test_overview_populated(admin_client):
    client, admin = admin_client
    _insert_metric(user_id=admin.id, thumbs="up")
    _insert_metric(user_id=admin.id, thumbs="down")
    _insert_metric(user_id="other", thumbs="up")

    overview_cache.clear()
    r = client.get("/api/v1/admin/overview/")
    assert r.status_code == 200
    body = r.json()
    assert body["chats_today"] == 3
    assert body["tokens_today"] == 3 * 30  # 10+20 each
    assert body["active_users_24h"] == 2
    # 2 ups / 1 down = 2/3
    assert body["thumbs_ratio_7d"] == pytest.approx(2 / 3)


# ---------------- Audit pagination ----------------


def test_audit_pagination(admin_client):
    client, _ = admin_client
    base = int(time.time()) - 1000
    # 55 rows with monotonic created_at so ordering is deterministic
    for i in range(55):
        _insert_audit(created_at=base + i, id=f"aud-{i:03d}", method="POST", path=f"/p/{i}")

    # Also the implicit audit rows from the admin's own login etc. — filter to ours.
    r = client.get("/api/v1/admin/audit/?limit=50&action=POST")
    assert r.status_code == 200
    p1 = r.json()
    assert len(p1["rows"]) == 50
    assert p1["next_cursor"] is not None

    r2 = client.get(f"/api/v1/admin/audit/?limit=50&action=POST&cursor={p1['next_cursor']}")
    assert r2.status_code == 200
    p2 = r2.json()
    # 55 seeded + N implicit admin auth rows → at least 5 remain; they'll fit on page 2.
    assert len(p2["rows"]) >= 5

    # No row overlap
    page1_ids = {row["id"] for row in p1["rows"]}
    page2_ids = {row["id"] for row in p2["rows"]}
    assert page1_ids.isdisjoint(page2_ids)


def test_audit_last_page_has_null_cursor(admin_client):
    client, _ = admin_client
    # Only one extra row → single page, next_cursor=null.
    _insert_audit(method="DELETE", path="/only")
    r = client.get("/api/v1/admin/audit/?action=DELETE&limit=50")
    assert r.status_code == 200
    body = r.json()
    assert body["next_cursor"] is None
    assert len(body["rows"]) == 1


# ---------------- Metrics filters ----------------


def test_metrics_filters(admin_client):
    client, admin = admin_client
    _insert_metric(user_id=admin.id, thumbs="up", db_id="california_schools", agent_mode="basic")
    _insert_metric(user_id=admin.id, thumbs="down", db_id="california_schools", agent_mode="agentic")
    _insert_metric(user_id="other", thumbs="up", db_id="toxicology", agent_mode="basic")

    # user filter
    r = client.get(f"/api/v1/admin/metrics/?user={admin.id}")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 2
    assert all(r["user_id"] == admin.id for r in rows)

    # thumbs filter
    r = client.get("/api/v1/admin/metrics/?thumbs=up")
    rows = r.json()["rows"]
    assert len(rows) == 2
    assert all(r["thumbs"] == "up" for r in rows)

    # db + agent_mode filter
    r = client.get("/api/v1/admin/metrics/?db=toxicology&agent_mode=basic")
    rows = r.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["db_id"] == "toxicology"

    # from/to filter — narrow to a tiny window that matches none
    r = client.get("/api/v1/admin/metrics/?from=1&to=2")
    assert r.json()["rows"] == []
