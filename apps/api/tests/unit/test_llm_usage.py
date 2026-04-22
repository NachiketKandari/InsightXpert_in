"""Phase 1.2 — unified LLM usage emission helper + 4 wired sites.

Covers:
  1. helper writes a row with computed cost
  2. helper never raises even when the engine is broken
  3. chat ``record_turn`` stamps source + cost fields
  4. profile runner emits a usage row on run
  5. automation runner emits when tokens were consumed
  6. trigger-compile emits when tokens were consumed
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from insightxpert_api.db.engine import get_engine
from insightxpert_api.metrics import record_llm_usage, record_turn
from insightxpert_api.metrics.pricing import PRICING_VERSION
from insightxpert_api.metrics.table import query_metrics


def _rows() -> list[dict]:
    engine = get_engine()
    with engine.begin() as conn:
        return [
            dict(r._mapping)
            for r in conn.execute(select(query_metrics)).fetchall()
        ]


# ---------------------------------------------------------------------------
# 1. helper writes
# ---------------------------------------------------------------------------


def test_record_llm_usage_writes_row(fresh_db) -> None:
    row_id = record_llm_usage(
        source="profile",
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=10_000,
        output_tokens=2_000,
        user_id="u1",
        source_ref_id="db-xyz",
        db_id="db-xyz",
    )
    assert row_id

    rows = _rows()
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "profile"
    assert r["provider"] == "gemini"
    assert r["model"] == "gemini-2.5-flash"
    assert r["source_ref_id"] == "db-xyz"
    assert r["pricing_version"] == PRICING_VERSION
    # 10_000×0.30/1M + 2_000×2.50/1M = 0.003 + 0.005 = 0.008
    assert r["cost_usd"] == pytest.approx(0.008, abs=1e-9)


# ---------------------------------------------------------------------------
# 2. helper swallows DB errors — never raises
# ---------------------------------------------------------------------------


def test_record_llm_usage_never_raises(monkeypatch, fresh_db) -> None:
    class _BrokenEngine:
        def begin(self):
            raise RuntimeError("database exploded")

    monkeypatch.setattr(
        "insightxpert_api.metrics.llm_usage.get_engine", lambda: _BrokenEngine()
    )

    # Must not raise, just log.
    row_id = record_llm_usage(
        source="chat",
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=200,
        user_id="u1",
    )
    assert row_id  # uuid still returned for log correlation


# ---------------------------------------------------------------------------
# 3. chat record_turn stamps source + cost
# ---------------------------------------------------------------------------


def test_record_turn_stamps_source_and_cost(fresh_db) -> None:
    record_turn(
        user_id="u1",
        conversation_id="c1",
        db_id="d1",
        question="how many rows?",
        final_sql="SELECT 1",
        agent_mode="basic",
        tokens_in=5_000,
        tokens_out=1_000,
        duration_ms=42,
        source="chat",
        provider="gemini",
        model="gemini-2.5-flash",
    )
    rows = _rows()
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "chat"
    assert r["provider"] == "gemini"
    assert r["model"] == "gemini-2.5-flash"
    assert r["cost_usd"] is not None
    assert r["cost_usd"] > 0
    assert r["pricing_version"] == PRICING_VERSION


# ---------------------------------------------------------------------------
# 4. profile runner emits
# ---------------------------------------------------------------------------


class _FakeLLM:
    model = "gemini-2.5-flash"

    def __init__(self) -> None:
        self.input_tokens_used = 0
        self.output_tokens_used = 0

    async def async_generate(self, prompt: str) -> str:  # simulate a token-burning call
        self.input_tokens_used += 1_000
        self.output_tokens_used += 500
        return '{}'  # empty JSON — triggers per-column fallback, but that's fine


@pytest.mark.asyncio
async def test_profile_runner_emits_usage(fresh_db, tmp_path) -> None:
    import sqlite3 as _sqlite

    from insightxpert_api.profiling.runner import (
        ProfileFlags,
        _reset_profile_semaphore,
        run_profile_stream,
    )
    from insightxpert_api.sse.emitter import EventEmitter

    _reset_profile_semaphore(4)

    # Tiny DB with one table, one column.
    db_file = tmp_path / "mini.sqlite"
    conn = _sqlite.connect(db_file)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
    conn.commit()
    conn.close()

    llm = _FakeLLM()
    # Pre-burn some tokens on the adapter to make sure the runner uses the
    # *delta*, not the absolute counter, to attribute this run.
    llm.input_tokens_used = 999
    llm.output_tokens_used = 999
    emitter = EventEmitter("convo-x")

    await run_profile_stream(
        emitter,
        db_id="db-profile-test",
        db_path=str(db_file),
        flags=ProfileFlags(with_summaries=True),
        llm=llm,
        batch_size=20,
        max_columns_for_llm=500,
        user_id="user-profile",
        provider="gemini",
        model="gemini-2.5-flash",
    )

    rows = _rows()
    profile_rows = [r for r in rows if r["source"] == "profile"]
    assert len(profile_rows) == 1
    r = profile_rows[0]
    assert r["user_id"] == "user-profile"
    assert r["source_ref_id"] == "db-profile-test"
    assert r["provider"] == "gemini"
    assert r["model"] == "gemini-2.5-flash"
    # Delta only, not absolute — adapter carried 999+999 pre-run. The
    # summaries stage makes 1 batch call + 2 per-column fallbacks (the fake
    # returns empty JSON), so exactly 3 calls × 1000 / 500 tokens each.
    assert r["tokens_in"] == 3_000
    assert r["tokens_out"] == 1_500


# ---------------------------------------------------------------------------
# 5. automation runner emits when tokens delta > 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_automation_runner_emits_usage_when_tokens_burned(fresh_db) -> None:
    """Runner wrapper records a usage row when llm_for_run tokens moved."""
    from insightxpert_api.automations import runner as r

    # Seed an automation with no sql queries so _execute_one takes the
    # early-return "no sql queries" path; but we bump the LLM token counter
    # *before* entering so the delta measurement non-zero and emission fires.
    fake_llm = _FakeLLM()

    class _AppState:
        llm = fake_llm

    class _App:
        state = _AppState()

    with patch.object(
        r.repository,
        "get_automation",
        return_value={
            "id": "a1",
            "db_id": "db1",
            "owner_user_id": "owner-automation",
            "name": "test",
            "is_active": True,
            "sql_queries_json": "[]",
        },
    ), patch.object(r.repository, "insert_run"), patch.object(
        r.AutomationService, "mark_run_completed"
    ), patch.object(r.repository, "list_triggers", return_value=[]):
        # Simulate the LLM being hit during the run: bump counters mid-flight
        # via a wrapped get_automation that also tweaks the adapter.
        original = r.repository.get_automation

        def _side_effect(aid):
            fake_llm.input_tokens_used += 2_500
            fake_llm.output_tokens_used += 700
            return original(aid)

        with patch.object(r.repository, "get_automation", side_effect=_side_effect):
            await r._execute_one(_App(), "a1")

    rows = _rows()
    autom_rows = [r for r in rows if r["source"] == "automation"]
    assert len(autom_rows) == 1
    row = autom_rows[0]
    assert row["user_id"] == "owner-automation"
    assert row["source_ref_id"] == "a1"
    assert row["tokens_in"] == 2_500
    assert row["tokens_out"] == 700


# ---------------------------------------------------------------------------
# 6. trigger-compile emits
# ---------------------------------------------------------------------------


def test_trigger_compile_emits_usage(user_client_automations) -> None:
    """/compile-trigger records source='trigger_compile' when LLM tokens move."""
    client, user = user_client_automations

    # Inject a fake LLM that increments token counters on .chat() and
    # returns a valid trigger JSON blob.
    class _FakeResp:
        def __init__(self, content: str) -> None:
            self.content = content
            self.input_tokens = 1_500
            self.output_tokens = 400

    class _FakeLLMSync:
        model = "gemini-2.5-flash"

        def __init__(self) -> None:
            self.input_tokens_used = 0
            self.output_tokens_used = 0

        async def chat(self, messages, tools=None, force_tool_use=False):
            self.input_tokens_used += 1_500
            self.output_tokens_used += 400
            return _FakeResp(
                '{"type": "threshold", "operator": "gt", "value": 5}'
            )

    fake_llm = _FakeLLMSync()
    client.app.state.llm = fake_llm

    resp = client.post(
        "/api/v1/automations/compile-trigger",
        json={"nl_text": "when x > 5", "available_columns": ["x"]},
    )
    assert resp.status_code == 200

    rows = _rows()
    tc_rows = [r for r in rows if r["source"] == "trigger_compile"]
    assert len(tc_rows) == 1
    r = tc_rows[0]
    assert r["user_id"] == user.id
    assert r["tokens_in"] == 1_500
    assert r["tokens_out"] == 400
    assert r["provider"] == "gemini"
