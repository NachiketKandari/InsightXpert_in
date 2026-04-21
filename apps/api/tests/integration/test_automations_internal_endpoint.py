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
    client = TestClient(create_app())
    body = json.dumps({"tick_at": 12345}).encode()
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
