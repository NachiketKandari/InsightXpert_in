"""One-line Protocol alias for the streaming-agent contract.

Every agent is a bare ``async def X_loop(...)`` that yields ``ChatChunk``
instances. This Protocol exists so routers / registries can depend on a
nominal type without forcing any agent to inherit from a base class.

The Protocol is structural (PEP 544). ``Any`` is used as the yielded element
type so the alias does not couple to a specific ``ChatChunk`` definition
(our ``insightxpert_api.sse.chunks.ChatChunk`` and the vendored
``agents_core.api.models.ChatChunk`` both satisfy it).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Agent(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]: ...
