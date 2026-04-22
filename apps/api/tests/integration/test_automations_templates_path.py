"""Regression: /api/v1/automations/templates must resolve to the templates
router, not the GET-by-id endpoint (automation_id="templates")."""

from __future__ import annotations


def test_templates_list_not_shadowed_by_get_by_id(user_client_automations):
    client, _ = user_client_automations
    # Empty list is fine — we just need the path to route to the templates handler.
    r = client.get("/api/v1/automations/templates")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_templates_crud_under_automations_prefix(user_client_automations):
    client, _ = user_client_automations

    created = client.post(
        "/api/v1/automations/templates",
        json={
            "name": "high-value",
            "description": "tx over 10k",
            "conditions": [
                {"type": "threshold", "column": "amount_inr",
                 "operator": "gt", "value": 10000}
            ],
        },
    ).json()
    tid = created["id"]

    # GET by id
    got = client.get(f"/api/v1/automations/templates/{tid}")
    assert got.status_code == 200
    assert got.json()["name"] == "high-value"

    # DELETE
    rm = client.delete(f"/api/v1/automations/templates/{tid}")
    assert rm.status_code == 200
