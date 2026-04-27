"""Integration tests for the automations CRUD API."""

from __future__ import annotations


def _create_payload(**overrides):
    base = {
        "name": "tx check",
        "nl_query": "count rows",
        "sql_queries": ["SELECT COUNT(*) AS n FROM molecule"],
        "db_id": "toxicology",
        "schedule_preset": "daily",
        "trigger_conditions": [
            {"type": "threshold", "operator": "gt", "value": 0, "column": "n"}
        ],
    }
    base.update(overrides)
    return base


def test_create_read_list_delete(user_client_automations):
    client, user = user_client_automations

    # create
    r = client.post("/api/v1/automations", json=_create_payload())
    assert r.status_code == 200, r.text
    auto = r.json()
    auto_id = auto["id"]
    assert auto["owner_user_id"] == user.id
    assert auto["is_active"] is True
    assert auto["next_run_at"] is not None
    assert len(auto["trigger_conditions"]) == 1

    # get
    r = client.get(f"/api/v1/automations/{auto_id}")
    assert r.status_code == 200
    assert r.json()["id"] == auto_id

    # list
    r = client.get("/api/v1/automations")
    assert r.status_code == 200
    assert any(a["id"] == auto_id for a in r.json())

    # delete
    r = client.delete(f"/api/v1/automations/{auto_id}")
    assert r.status_code == 200

    # 404 on follow-up fetch
    r = client.get(f"/api/v1/automations/{auto_id}")
    assert r.status_code == 404


def test_update_triggers_replaced(user_client_automations):
    client, _ = user_client_automations
    r = client.post("/api/v1/automations", json=_create_payload())
    assert r.status_code == 200
    auto_id = r.json()["id"]

    new_conditions = [
        {"type": "row_count", "operator": "gte", "value": 1},
        {"type": "threshold", "operator": "lt", "value": 100, "column": "n"},
    ]
    r = client.put(
        f"/api/v1/automations/{auto_id}",
        json={"trigger_conditions": new_conditions, "name": "tx check v2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "tx check v2"
    assert len(body["trigger_conditions"]) == 2
    assert body["trigger_conditions"][0]["type"] == "row_count"


def test_toggle_flips_active(user_client_automations):
    client, _ = user_client_automations
    auto_id = client.post("/api/v1/automations", json=_create_payload()).json()["id"]

    r = client.post(f"/api/v1/automations/{auto_id}/toggle")
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = client.post(f"/api/v1/automations/{auto_id}/toggle")
    assert r.status_code == 200
    assert r.json()["is_active"] is True


def test_non_owner_cannot_see_automation(fresh_db, automations_env):
    from fastapi.testclient import TestClient

    from insightxpert_api.main import create_app
    from insightxpert_api.users import service
    from insightxpert_api.users.models import CreateUserInput

    a = service.invite(CreateUserInput(email="a@example.com", role="user"))
    b = service.invite(CreateUserInput(email="b@example.com", role="user"))

    client_a = TestClient(create_app())
    client_a.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": a.temp_password},
    )
    auto_id = client_a.post(
        "/api/v1/automations", json=_create_payload()
    ).json()["id"]

    client_b = TestClient(create_app())
    client_b.post(
        "/api/v1/auth/login",
        json={"email": "b@example.com", "password": b.temp_password},
    )
    r = client_b.get(f"/api/v1/automations/{auto_id}")
    assert r.status_code == 403

    r = client_b.get("/api/v1/automations")
    assert r.status_code == 200
    assert r.json() == []


def test_admin_sees_all_automations(fresh_db, automations_env):
    from fastapi.testclient import TestClient

    from insightxpert_api.main import create_app
    from insightxpert_api.users import service
    from insightxpert_api.users.models import CreateUserInput

    a = service.invite(CreateUserInput(email="a@example.com", role="user"))
    adm = service.invite(CreateUserInput(email="ad@example.com", role="admin"))

    client_a = TestClient(create_app())
    client_a.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": a.temp_password},
    )
    client_a.post("/api/v1/automations", json=_create_payload(name="a-one"))

    client_adm = TestClient(create_app())
    client_adm.post(
        "/api/v1/auth/login",
        json={"email": "ad@example.com", "password": adm.temp_password},
    )
    r = client_adm.get("/api/v1/automations")
    assert r.status_code == 200
    names = [x["name"] for x in r.json()]
    assert "a-one" in names


def test_delete_cascades_to_triggers_and_runs(user_client_automations):
    """Deleting an automation must cascade to triggers + runs per migration FK."""
    from insightxpert_api.automations import repository

    client, _ = user_client_automations
    auto_id = client.post("/api/v1/automations", json=_create_payload()).json()["id"]

    # Insert a fake run directly via repository
    repository.insert_run({
        "automation_id": auto_id,
        "status": "success",
        "row_count": 1,
    })
    assert len(repository.list_runs(auto_id)) == 1
    assert len(repository.list_triggers(auto_id)) == 1

    r = client.delete(f"/api/v1/automations/{auto_id}")
    assert r.status_code == 200

    assert repository.list_runs(auto_id) == []
    assert repository.list_triggers(auto_id) == []


def test_create_rejects_write_sql(user_client_automations):
    client, _ = user_client_automations
    r = client.post(
        "/api/v1/automations",
        json=_create_payload(sql_queries=["DELETE FROM molecule"]),
    )
    assert r.status_code == 400
    assert "forbidden" in r.json()["detail"].lower() or "select" in r.json()["detail"].lower()


def test_create_rejects_multi_statement_sql(user_client_automations):
    client, _ = user_client_automations
    r = client.post(
        "/api/v1/automations",
        json=_create_payload(sql_queries=["SELECT 1; SELECT 2"]),
    )
    assert r.status_code == 400


def test_create_blocked_when_user_at_cap(user_client_automations, monkeypatch):
    from insightxpert_api.config import get_settings

    # Monkeypatch the cached settings instance directly. This is more robust
    # than relying on env var ordering since get_settings() is @lru_cache'd.
    settings = get_settings()
    monkeypatch.setattr(settings, "automations_max_per_user", 2)

    client, _ = user_client_automations
    for i in range(2):
        r = client.post(
            "/api/v1/automations", json=_create_payload(name=f"a{i}")
        )
        assert r.status_code == 200, r.text

    over = client.post(
        "/api/v1/automations", json=_create_payload(name="over")
    )
    assert over.status_code == 429, over.text
    detail = over.json().get("detail", "").lower()
    assert "limit" in detail


def test_create_with_unknown_db_id_returns_400(user_client_automations):
    client, _ = user_client_automations
    r = client.post(
        "/api/v1/automations",
        json=_create_payload(db_id="does-not-exist-xyz"),
    )
    assert r.status_code == 400
    assert "db_id" in r.json().get("detail", "").lower()


def test_list_automations_legacy_shape(user_client_automations):
    """Without limit/offset query params, list returns a bare array (FE compat)."""
    client, _ = user_client_automations
    client.post("/api/v1/automations", json=_create_payload(name="a"))
    r = client.get("/api/v1/automations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_automations_paginated_envelope(user_client_automations):
    client, _ = user_client_automations
    for i in range(5):
        r = client.post(
            "/api/v1/automations", json=_create_payload(name=f"a{i}")
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/automations?limit=2&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2

    r = client.get("/api/v1/automations?limit=2&offset=4")
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 1


def test_list_templates_paginated_envelope(user_client_automations):
    client, _ = user_client_automations
    for i in range(3):
        r = client.post(
            "/api/v1/automations/templates",
            json={
                "name": f"t{i}",
                "description": None,
                "conditions": [
                    {
                        "type": "threshold",
                        "operator": "gt",
                        "value": 0,
                        "column": "n",
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/automations/templates")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r = client.get("/api/v1/automations/templates?limit=1&offset=0")
    body = r.json()
    assert isinstance(body, dict)
    assert body["total"] == 3
    assert len(body["items"]) == 1


def test_create_rejects_bad_cron(user_client_automations):
    client, _ = user_client_automations
    r = client.post(
        "/api/v1/automations",
        json=_create_payload(cron_expression="not a cron", schedule_preset=None),
    )
    assert r.status_code == 422 or r.status_code == 400
