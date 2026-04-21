"""Integration tests for /api/v1/admin/prompts/*.

Covers RBAC, list-merge behavior (file vs DB override), PUT create/update,
DELETE and idempotent RESET.
"""

from __future__ import annotations


def test_non_admin_forbidden(user_client):
    client, _ = user_client
    assert client.get("/api/v1/admin/prompts/").status_code == 403
    assert client.get("/api/v1/admin/prompts/anything").status_code == 403
    assert (
        client.put(
            "/api/v1/admin/prompts/anything",
            json={"content": "hi"},
        ).status_code
        == 403
    )
    assert client.delete("/api/v1/admin/prompts/anything").status_code == 403
    assert client.post("/api/v1/admin/prompts/anything/reset").status_code == 403


def test_list_shows_file_prompts(admin_client):
    client, _ = admin_client
    r = client.get("/api/v1/admin/prompts/")
    assert r.status_code == 200
    rows = r.json()
    names = {row["name"] for row in rows}
    # At least the known bundled templates appear.
    assert "orchestrator_planner" in names
    assert "insight_quality_evaluator" in names
    for row in rows:
        # All pure-file prompts should report source=file, no override.
        if row["name"] in {"orchestrator_planner", "insight_quality_evaluator"}:
            assert row["source"] == "file"
            assert row["has_override"] is False
            assert row["is_active"] is False
            assert row["updated_at"] is None


def test_put_creates_override(admin_client):
    client, _ = admin_client
    r = client.put(
        "/api/v1/admin/prompts/orchestrator_planner",
        json={"content": "CUSTOM TEMPLATE", "description": "test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "CUSTOM TEMPLATE"
    assert body["source"] == "db"
    assert body["is_active"] is True
    assert body["description"] == "test"
    assert isinstance(body["updated_at"], int)
    assert body["file_content"] is not None  # bundled .j2 still visible

    # GET returns the override.
    g = client.get("/api/v1/admin/prompts/orchestrator_planner")
    assert g.status_code == 200
    gb = g.json()
    assert gb["content"] == "CUSTOM TEMPLATE"
    assert gb["source"] == "db"

    # List reflects override.
    lr = client.get("/api/v1/admin/prompts/")
    row = next(x for x in lr.json() if x["name"] == "orchestrator_planner")
    assert row["source"] == "db"
    assert row["has_override"] is True
    assert row["is_active"] is True


def test_put_updates_and_bumps_updated_at(admin_client):
    client, _ = admin_client
    r1 = client.put(
        "/api/v1/admin/prompts/orchestrator_planner",
        json={"content": "v1"},
    )
    assert r1.status_code == 200
    t1 = r1.json()["updated_at"]

    # A second PUT some ticks later must land at a >= timestamp (clock-second
    # granularity means equal is acceptable; content must update).
    import time as _t
    _t.sleep(1.05)
    r2 = client.put(
        "/api/v1/admin/prompts/orchestrator_planner",
        json={"content": "v2", "description": "updated"},
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["content"] == "v2"
    assert b2["description"] == "updated"
    assert b2["updated_at"] >= t1

    g = client.get("/api/v1/admin/prompts/orchestrator_planner").json()
    assert g["content"] == "v2"


def test_delete_reverts_to_file_source(admin_client):
    client, _ = admin_client
    client.put(
        "/api/v1/admin/prompts/orchestrator_planner",
        json={"content": "override"},
    )

    d = client.delete("/api/v1/admin/prompts/orchestrator_planner")
    assert d.status_code == 200
    assert d.json() == {"deleted": True}

    # GET now falls back to file content.
    g = client.get("/api/v1/admin/prompts/orchestrator_planner")
    assert g.status_code == 200
    assert g.json()["source"] == "file"

    # Second delete → 404.
    d2 = client.delete("/api/v1/admin/prompts/orchestrator_planner")
    assert d2.status_code == 404


def test_delete_missing_is_404(admin_client):
    client, _ = admin_client
    r = client.delete("/api/v1/admin/prompts/orchestrator_planner")
    assert r.status_code == 404


def test_reset_is_idempotent(admin_client):
    client, _ = admin_client
    client.put(
        "/api/v1/admin/prompts/orchestrator_planner",
        json={"content": "override"},
    )
    r1 = client.post("/api/v1/admin/prompts/orchestrator_planner/reset")
    assert r1.status_code == 200
    assert r1.json() == {"reset": True}
    # Second reset still succeeds — that's the whole point.
    r2 = client.post("/api/v1/admin/prompts/orchestrator_planner/reset")
    assert r2.status_code == 200
    assert r2.json() == {"reset": True}

    # After reset, list shows source=file again.
    lr = client.get("/api/v1/admin/prompts/")
    row = next(x for x in lr.json() if x["name"] == "orchestrator_planner")
    assert row["source"] == "file"
    assert row["has_override"] is False


def test_get_unknown_name_404(admin_client):
    client, _ = admin_client
    r = client.get("/api/v1/admin/prompts/no_such_prompt_xyz")
    assert r.status_code == 404
