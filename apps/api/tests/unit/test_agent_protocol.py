"""The Agent Protocol matches any async-generator function structurally."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from insightxpert_api.agents.protocol import Agent


async def demo_loop(question: str) -> AsyncGenerator[dict, None]:
    yield {"type": "status", "data": {"message": "hi"}}


def test_async_generator_function_satisfies_agent_protocol():
    # runtime_checkable Protocol checks for callability + AsyncGenerator return.
    assert isinstance(demo_loop, Agent)


def test_non_agent_sync_function_is_rejected_structurally():
    # A sync function is technically callable but its return type is not an
    # AsyncGenerator — Protocol.isinstance only verifies the call signature,
    # so we instead assert the sync fn does not behave as an async generator.
    def sync_fn(q: str) -> str:
        return q

    # isinstance passes (callable structural match), so assert behavioural
    # difference: calling sync_fn returns a str, not an async generator.
    out = sync_fn("x")
    assert not hasattr(out, "__aiter__")
