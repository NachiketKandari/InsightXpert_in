"""Tests for the HMAC-signed internal scheduler endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from insightxpert_api.main import create_app


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_internal_endpoint_returns_503_when_flag_off(fresh_db):
    client = TestClient(create_app())
    body = json.dumps({"tick_at": 0}).encode()
    r = client.post(
        "/api/internal/run-due-automations",
        content=body,
        headers={"X-Scheduler-Signature": _sign("x" * 40, body)},
    )
    assert r.status_code == 503


def test_internal_endpoint_accepts_valid_signature(fresh_db, automations_external_env):
    import time

    client = TestClient(create_app())
    # Must be a fresh tick_at — MF2 rejects stale values >5min off.
    body = json.dumps({"tick_at": int(time.time())}).encode()
    sig = _sign("x" * 40, body)
    r = client.post(
        "/api/internal/run-due-automations",
        content=body,
        headers={
            "X-Scheduler-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert "ran" in r.json()


def test_internal_endpoint_rejects_bad_signature(fresh_db, automations_external_env):
    client = TestClient(create_app())
    body = json.dumps({"tick_at": 0}).encode()
    r = client.post(
        "/api/internal/run-due-automations",
        content=body,
        headers={"X-Scheduler-Signature": "deadbeef"},
    )
    assert r.status_code == 401


def test_internal_endpoint_rejects_missing_signature(fresh_db, automations_external_env):
    client = TestClient(create_app())
    body = json.dumps({"tick_at": 0}).encode()
    r = client.post("/api/internal/run-due-automations", content=body)
    assert r.status_code == 401


def test_stale_tick_at_rejected(fresh_db, automations_external_env):
    """MF2: tick_at >5min in the past must 401, even with a valid signature.
    Otherwise an attacker who captures one request can replay it forever.
    """
    import time

    client = TestClient(create_app())
    stale_body = json.dumps({"tick_at": int(time.time()) - 600}).encode()
    sig = _sign("x" * 40, stale_body)
    r = client.post(
        "/api/internal/run-due-automations",
        content=stale_body,
        headers={
            "X-Scheduler-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
    assert "stale" in r.json().get("detail", "").lower()


def test_401_writes_audit_row(fresh_db, automations_external_env):
    """MF2: unauthorized hits must land in audit_log for detection.

    Relies on the existing AuditMiddleware, which captures every mutating
    request regardless of resource_type classification. Using a context
    manager ensures the lifespan's queue stop() drains pending rows.
    """
    import time

    from insightxpert_api.audit.queue import reset_queue_for_tests
    from sqlalchemy import create_engine, text

    reset_queue_for_tests()
    with TestClient(create_app()) as client:
        client.post(
            "/api/internal/run-due-automations",
            json={"tick_at": 1},
            headers={"X-Scheduler-Signature": "deadbeef"},
        )

        engine = create_engine(fresh_db)
        deadline = time.monotonic() + 5.0
        count = 0
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                count = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM audit_log "
                        "WHERE path LIKE '%run-due-automations%' "
                        "AND status_code = 401"
                    )
                ).scalar() or 0
            if count:
                break
            time.sleep(0.1)

    assert count >= 1


def test_internal_endpoint_503_when_embedded_mode(fresh_db, automations_env):
    """MF4: when scheduler_mode=embedded, the external cron endpoint must
    NOT be allowed to fire — 503 prevents double-runs with the in-process
    scheduler. ``automations_env`` fixture sets mode=embedded.
    """
    import time

    client = TestClient(create_app())
    r = client.post(
        "/api/internal/run-due-automations",
        json={"tick_at": int(time.time())},
        headers={"X-Scheduler-Signature": "anything"},
    )
    assert r.status_code == 503
