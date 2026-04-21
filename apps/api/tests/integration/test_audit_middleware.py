"""Audit middleware + lifespan-managed queue: a real login POST lands in audit_log."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def test_login_post_produces_audit_row(fresh_db):
    from insightxpert_api.audit.queue import reset_queue_for_tests
    from insightxpert_api.main import create_app
    from insightxpert_api.users import service
    from insightxpert_api.users.models import CreateUserInput

    reset_queue_for_tests()
    invited = service.invite(CreateUserInput(email="audituser@example.com", role="user"))

    with TestClient(create_app()) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "audituser@example.com", "password": invited.temp_password},
        )
        assert resp.status_code == 200

        # Allow the batched worker a moment to flush (batch_interval_ms=200 by default).
        engine = create_engine(fresh_db)
        deadline = time.monotonic() + 5.0
        rows: list = []
        while time.monotonic() < deadline:
            with engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT method, path, status_code, resource_type "
                    "FROM audit_log WHERE path = '/api/v1/auth/login'"
                )).fetchall()
            if rows:
                break
            time.sleep(0.1)

    assert len(rows) >= 1
    row = rows[0]
    assert row.method == "POST"
    assert row.path == "/api/v1/auth/login"
    assert row.status_code == 200
    assert row.resource_type == "auth.session"
