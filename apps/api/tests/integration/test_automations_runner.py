"""Integration tests for runner.run_due_automations.

Uses the bundled ``toxicology.sqlite`` — molecule table. A trigger that
fires produces a run with status=success + a notification row; a trigger
that does not fire produces a run with status=no_trigger + no notification.
"""

from __future__ import annotations

import json

from insightxpert_api.automations import repository, runner


def _create(client, **overrides):
    body = {
        "name": "tx",
        "nl_query": "q",
        "sql_queries": ["SELECT COUNT(*) AS n FROM molecule"],
        "db_id": "toxicology",
        "schedule_preset": "daily",
        "trigger_conditions": [
            {"type": "threshold", "operator": "gt", "value": 0, "column": "n"}
        ],
    }
    body.update(overrides)
    r = client.post("/api/v1/automations", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def test_runner_fires_trigger_and_creates_notification(user_client_automations):
    client, user = user_client_automations
    auto = _create(client)

    result = await runner.run_due_automations(
        None, automation_id=auto["id"]
    )
    assert len(result.ran) == 1
    assert result.ran[0].status == "success"

    runs = repository.list_runs(auto["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "success"

    # Notification row exists for owner
    notifs = repository.list_notifications(user.id)
    assert len(notifs) == 1
    assert notifs[0]["automation_id"] == auto["id"]
    assert notifs[0]["severity"] == "warning"


async def test_runner_no_trigger_does_not_notify(user_client_automations):
    client, user = user_client_automations
    auto = _create(
        client,
        trigger_conditions=[
            {"type": "row_count", "operator": "lt", "value": 0}
        ],
    )

    result = await runner.run_due_automations(
        None, automation_id=auto["id"]
    )
    assert result.ran[0].status == "no_trigger"

    assert repository.count_unread(user.id) == 0


async def test_runner_records_error_on_bad_sql(fresh_db, automations_env):
    """Directly insert an automation with invalid SQL via repo to bypass
    the route validator, then run to see the error path."""
    from insightxpert_api.automations import repository as repo
    from insightxpert_api.users import service as users_svc
    from insightxpert_api.users.models import CreateUserInput
    import uuid
    import time

    user = users_svc.invite(CreateUserInput(email="bad@example.com", role="user")).user

    auto_id = str(uuid.uuid4())
    repo.insert_automation({
        "id": auto_id,
        "name": "bad",
        "description": None,
        "nl_query": "q",
        "sql_queries_json": json.dumps(["SELECT * FROM no_such_table"]),
        "db_id": "toxicology",
        "cron_expression": "* * * * *",
        "is_active": True,
        "owner_user_id": user.id,
        "source_conversation_id": None,
        "source_message_id": None,
        "workflow_graph_json": None,
        "last_run_at": None,
        "next_run_at": int(time.time()),
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    })
    result = await runner.run_due_automations(None, automation_id=auto_id)
    assert result.ran[0].status == "error"
    runs = repo.list_runs(auto_id)
    assert runs[0]["status"] == "error"
    assert runs[0]["error_message"]


async def test_run_due_picks_up_active_with_past_next_run_at(user_client_automations):
    """Pass now=<very large> so all active automations are 'due'."""
    client, _ = user_client_automations
    auto = _create(client)
    result = await runner.run_due_automations(None, now=10**10)
    assert any(item.automation_id == auto["id"] for item in result.ran)
