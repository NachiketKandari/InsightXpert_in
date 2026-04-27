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


async def test_batch_runs_parallel(user_client_automations, monkeypatch):
    """MF1 regression: two due automations each with a simulated 0.2s SQL
    should finish the batch in ~0.2s (parallel), not ~0.4s (serial).

    Tolerance <0.35s leaves margin for CI noise but still catches serial.
    """
    import asyncio
    import time

    from insightxpert_api.automations import runner as runner_mod
    from insightxpert_api.automations.models import RunBatchItem

    client, _user = user_client_automations
    # Create two automations via the API so they land in the DB with normal
    # defaults; then force both due by rewriting next_run_at.
    auto_ids: list[str] = []
    for i in range(2):
        r = client.post(
            "/api/v1/automations",
            json={
                "name": f"p{i}",
                "nl_query": "x",
                "sql_queries": ["SELECT COUNT(*) AS n FROM molecule"],
                "db_id": "toxicology",
                "schedule_preset": "daily",
                "trigger_conditions": [],
            },
        )
        assert r.status_code == 200, r.text
        auto_ids.append(r.json()["id"])

    from sqlalchemy import text

    from insightxpert_api.db.engine import get_engine

    now = int(time.time())
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE automations SET next_run_at = :n, is_active = 1"),
            {"n": now},
        )

    # Patch _execute_one to sleep 0.2s and return a stub — we don't need
    # the real run to happen here; we just need the gather plumbing to be
    # exercised in parallel.
    async def slow(app, aid):
        await asyncio.sleep(0.2)
        return RunBatchItem(automation_id=aid, status="success")

    monkeypatch.setattr(runner_mod, "_execute_one", slow)

    t0 = time.perf_counter()
    result = await runner_mod.run_due_automations(None, now=now)
    elapsed = time.perf_counter() - t0
    assert len(result.ran) == 2
    assert elapsed < 0.35, f"batch took {elapsed:.2f}s — expected parallel"


async def test_run_emits_structured_logs(user_client_automations, monkeypatch):
    """MF3 regression: each run must emit run_started + run_completed at
    minimum, and trigger_fired when a condition fires. We intercept the
    bound logger's info() calls directly — structlog's PrintLoggerFactory
    emits via sys.stdout, which pytest's capsys doesn't cooperate with
    cleanly when the structlog logger was cached earlier.
    """
    from insightxpert_api.automations import runner as runner_mod

    events: list[tuple[str, str, dict]] = []

    class _Capture:
        def _capture(self, level):
            def _log(event, **kw):
                events.append((level, event, kw))
            return _log
        info = property(lambda self: self._capture("info"))
        warning = property(lambda self: self._capture("warning"))
        error = property(lambda self: self._capture("error"))

    monkeypatch.setattr(runner_mod, "log", _Capture())

    client, _ = user_client_automations
    auto = _create(client)  # has a threshold trigger that will fire

    await runner_mod.run_due_automations(None, automation_id=auto["id"])

    event_names = {evt for _lvl, evt, _kw in events}
    assert "automation.run_started" in event_names
    assert "automation.run_completed" in event_names
    assert "automation.trigger_fired" in event_names


async def test_token_accounting_records_source_ref_id_as_run_id(
    user_client_automations,
):
    """Track 1.3 regression: when an automation run consumes LLM tokens,
    the recorded ``query_metrics`` row's ``source_ref_id`` must be the
    persisted ``automation_runs.id`` (not the automation_id, and not None).

    We simulate token consumption by stamping ``input_tokens_used`` /
    ``output_tokens_used`` on a dummy ``app.state.llm`` between a
    pre-call snapshot (taken inside the runner) and post-call read.
    """
    from sqlalchemy import select

    from insightxpert_api.automations import repository as auto_repo
    from insightxpert_api.automations import runner as runner_mod
    from insightxpert_api.db.engine import get_engine
    from insightxpert_api.metrics.table import query_metrics

    client, _user = user_client_automations
    auto = _create(client)

    class _LLM:
        # Counters increment as a side-effect of _execute_one calling the
        # patched insert_run wrapper; simpler: bump them directly via a
        # patched repository.insert_run that also stamps the LLM.
        model = "gemini-test"
        input_tokens_used = 0
        output_tokens_used = 0

    fake_llm = _LLM()

    class _AppState:
        llm = fake_llm

    class _App:
        state = _AppState()

    # Bump token counters between snapshot and finally — patch insert_run so
    # the act of persisting the run also "consumes" tokens, which mirrors
    # what would happen if the runner had invoked the LLM mid-run.
    real_insert_run = auto_repo.insert_run

    def _insert_and_consume(values):
        fake_llm.input_tokens_used += 10
        fake_llm.output_tokens_used += 5
        return real_insert_run(values)

    import unittest.mock as _mock

    with _mock.patch.object(runner_mod.repository, "insert_run", _insert_and_consume):
        result = await runner_mod.run_due_automations(
            _App(), automation_id=auto["id"]
        )
    assert result.ran[0].status == "success"

    runs = auto_repo.list_runs(auto["id"])
    assert len(runs) == 1
    persisted_run_id = runs[0]["id"]

    with get_engine().connect() as conn:
        rows = conn.execute(
            select(query_metrics).where(query_metrics.c.source == "automation")
        ).all()
    assert len(rows) == 1, "exactly one automation usage row expected"
    row = dict(rows[0]._mapping)
    assert row["source_ref_id"] == persisted_run_id, (
        f"source_ref_id should be the persisted run id, got "
        f"{row['source_ref_id']!r} vs run {persisted_run_id!r}"
    )
    assert row["tokens_in"] == 10
    assert row["tokens_out"] == 5


async def test_two_concurrent_run_due_calls_each_run_once(
    user_client_automations, monkeypatch
):
    """Multi-replica regression: when two run_due_automations calls race
    on the same tick, the atomic claim must ensure each due automation is
    handed to exactly one caller. Simulates two replicas on the same DB.
    """
    import asyncio
    import time

    from sqlalchemy import text

    from insightxpert_api.automations import runner as runner_mod
    from insightxpert_api.automations.models import RunBatchItem
    from insightxpert_api.db.engine import get_engine

    client, _user = user_client_automations
    auto_ids: list[str] = []
    for i in range(4):
        r = client.post(
            "/api/v1/automations",
            json={
                "name": f"r{i}",
                "nl_query": "x",
                "sql_queries": ["SELECT COUNT(*) AS n FROM molecule"],
                "db_id": "toxicology",
                "schedule_preset": "daily",
                "trigger_conditions": [],
            },
        )
        assert r.status_code == 200, r.text
        auto_ids.append(r.json()["id"])

    now = int(time.time())
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE automations SET next_run_at = :n, is_active = 1"),
            {"n": now},
        )

    invocations: dict[str, int] = {}
    inv_lock = asyncio.Lock()

    async def counting_execute_one(_app, automation_id):
        async with inv_lock:
            invocations[automation_id] = invocations.get(automation_id, 0) + 1
        return RunBatchItem(automation_id=automation_id, status="success")

    monkeypatch.setattr(runner_mod, "_execute_one", counting_execute_one)

    a, b = await asyncio.gather(
        runner_mod.run_due_automations(None, now=now),
        runner_mod.run_due_automations(None, now=now),
    )
    ran_ids = [item.automation_id for item in a.ran] + [
        item.automation_id for item in b.ran
    ]
    assert sorted(ran_ids) == sorted(invocations.keys())
    assert all(v == 1 for v in invocations.values()), invocations
    assert set(invocations.keys()) == set(auto_ids)
