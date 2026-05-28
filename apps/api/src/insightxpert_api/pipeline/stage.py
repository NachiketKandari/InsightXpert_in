# DECISION(D-004): Stage Protocol for swappable pipeline — structural Protocol (PEP 544)
# defining Stage.input/output/name/run. No base class inheritance needed; vendored
# pipeline classes satisfy the contract without modification.
"""Stage Protocol and shared PipelineContext.

A ``Stage`` is any object with a ``name`` and an async ``run(ctx, input) -> output``. The
orchestrator composes a list of stages and threads a ``PipelineContext`` through them.

Stages read/write ``ctx.state`` for cross-stage data (``question``, ``db_id``, ``profile``,
``schema_text``, ``sql``, ``rows``, ``answer``, ...). They emit SSE chunks via ``ctx.emitter``
so the UI sees work-in-progress.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..sse.emitter import EventEmitter


@dataclass
class PipelineContext:
    """Per-request mutable context shared across stages."""

    session_id: str
    conversation_id: str
    emitter: EventEmitter | None = None
    state: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Stage(Protocol):
    """A step in the text-to-SQL pipeline."""

    name: str

    async def run(self, ctx: PipelineContext, input: Any) -> Any:  # noqa: A002
        """Run this stage. Return value becomes the next stage's input."""
        ...
