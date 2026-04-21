"""Integration tests for /api/v1/admin/rag/*.

Strategy: we monkeypatch ``rag.admin_service.clear_qa_pairs`` to avoid the
ChromaDB + ONNX embedding startup cost. This verifies the HTTP surface
(auth + status + response shape) deterministically; the vendored store's
``flush_qa_pairs`` behavior is already exercised by upstream tests.
"""

from __future__ import annotations


def test_non_admin_forbidden(user_client, monkeypatch):
    client, _ = user_client

    def _boom() -> int:
        raise AssertionError("admin route must reject non-admin before reaching service")

    monkeypatch.setattr(
        "insightxpert_api.rag.admin_service.clear_qa_pairs", _boom
    )
    r = client.delete("/api/v1/admin/rag/qa-pairs")
    assert r.status_code == 403


def test_admin_clear_qa_pairs(admin_client, monkeypatch):
    client, _ = admin_client
    calls = {"n": 0}

    def _fake_clear() -> int:
        calls["n"] += 1
        return 7

    monkeypatch.setattr(
        "insightxpert_api.rag.admin_service.clear_qa_pairs", _fake_clear
    )

    r = client.delete("/api/v1/admin/rag/qa-pairs")
    assert r.status_code == 200
    assert r.json() == {"deleted": True, "count": 7}
    assert calls["n"] == 1


def test_admin_clear_qa_pairs_zero(admin_client, monkeypatch):
    client, _ = admin_client
    monkeypatch.setattr(
        "insightxpert_api.rag.admin_service.clear_qa_pairs", lambda: 0
    )
    r = client.delete("/api/v1/admin/rag/qa-pairs")
    assert r.status_code == 200
    assert r.json() == {"deleted": True, "count": 0}
