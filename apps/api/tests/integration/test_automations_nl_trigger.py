"""NL trigger compile endpoint tests. LLM mocked."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock


@dataclass
class _FakeResp:
    content: str


async def test_compile_trigger_parses_valid_json(user_client_automations):
    client, _ = user_client_automations
    fake_llm = AsyncMock()
    fake_llm.chat = AsyncMock(
        return_value=_FakeResp(content='{"type":"threshold","operator":"gt","value":5,"column":"n"}')
    )
    # inject into app state
    client.app.state.llm = fake_llm
    r = client.post(
        "/api/v1/automations/compile-trigger",
        json={"nl_text": "when n is bigger than 5", "available_columns": ["n"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "threshold"
    assert body["nl_text"] == "when n is bigger than 5"


async def test_compile_trigger_falls_back_on_parse_failure(user_client_automations):
    client, _ = user_client_automations
    fake_llm = AsyncMock()
    fake_llm.chat = AsyncMock(return_value=_FakeResp(content="not json at all"))
    client.app.state.llm = fake_llm
    r = client.post(
        "/api/v1/automations/compile-trigger",
        json={"nl_text": "something"},
    )
    assert r.status_code == 200
    body = r.json()
    # threshold fallback
    assert body["type"] == "threshold"
    assert body["nl_text"] == "something"


async def test_generate_sql_returns_json(user_client_automations):
    client, _ = user_client_automations
    fake_llm = AsyncMock()
    fake_llm.chat = AsyncMock(
        return_value=_FakeResp(
            content='{"sql":"SELECT COUNT(*) FROM x","explanation":"counts rows"}'
        )
    )
    client.app.state.llm = fake_llm
    r = client.post(
        "/api/v1/automations/generate-sql", json={"prompt": "count rows"}
    )
    assert r.status_code == 200
    assert r.json()["sql"].startswith("SELECT")


async def test_compile_trigger_propagates_llm_outage(user_client_automations):
    """MF5 regression: when the LLM itself fails (TimeoutError, etc.) the
    compile_or_fallback path must NOT silently return the threshold-fallback
    — that would mask outages and let a "fire on anything > 0" trigger land
    in the DB. The narrowed except (ValueError, JSONDecodeError) ensures
    non-parse exceptions propagate out.
    """
    from insightxpert_api.automations import nl_trigger

    class _BoomLLM:
        async def chat(self, messages):
            raise TimeoutError("upstream LLM timed out")

    raised = False
    try:
        await nl_trigger.compile_or_fallback(_BoomLLM(), "anything")
    except TimeoutError:
        raised = True
    assert raised, (
        "TimeoutError from LLM must propagate (not be swallowed by the "
        "fallback clause)"
    )


async def test_compile_trigger_fallback_on_invalid_json_only(user_client_automations):
    """MF5 regression companion: invalid JSON output still falls back
    (the narrow except must cover the ValueError/JSONDecodeError path)."""
    from insightxpert_api.automations import nl_trigger

    class _BadJsonLLM:
        async def chat(self, messages):
            return _FakeResp(content="definitely not json")

    result = await nl_trigger.compile_or_fallback(_BadJsonLLM(), "hello")
    assert result["type"] == "threshold"
    assert result["nl_text"] == "hello"


async def test_compile_trigger_route_returns_502_on_llm_outage(user_client_automations):
    """SF9: route-level complement to the helper-level propagation test.
    When the LLM itself fails (TimeoutError / httpx / auth), the route must
    surface 502 "AI service unavailable" — not 422 "invalid trigger
    description", which misleads the FE into thinking the user's input
    was malformed."""
    client, _ = user_client_automations

    class _BoomLLM:
        async def chat(self, messages):
            raise TimeoutError("upstream LLM timed out")

    client.app.state.llm = _BoomLLM()
    r = client.post(
        "/api/v1/automations/compile-trigger",
        json={"nl_text": "alert when fraud > 100"},
    )
    assert r.status_code == 502, r.text
    assert "unavailable" in r.json()["detail"].lower()


async def test_compile_trigger_route_returns_422_on_value_error(user_client_automations):
    """SF9: ValueError from the helper (bad parse that somehow escaped the
    fallback, or any future input-validation path) must still map to 422."""
    from unittest.mock import patch

    client, _ = user_client_automations

    async def _raise_value_error(*args, **kwargs):
        raise ValueError("bad input shape")

    with patch(
        "insightxpert_api.automations.nl_trigger.compile_or_fallback",
        new=_raise_value_error,
    ):
        # LLM on state is irrelevant since we're patching the helper.
        r = client.post(
            "/api/v1/automations/compile-trigger",
            json={"nl_text": "anything"},
        )
    assert r.status_code == 422, r.text


async def test_generate_sql_422_on_bad_output(user_client_automations):
    client, _ = user_client_automations
    fake_llm = AsyncMock()
    fake_llm.chat = AsyncMock(return_value=_FakeResp(content="not json"))
    client.app.state.llm = fake_llm
    r = client.post(
        "/api/v1/automations/generate-sql", json={"prompt": "x"}
    )
    assert r.status_code == 422
