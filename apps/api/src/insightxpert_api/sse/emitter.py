"""Async event emitter used by pipeline stages to push SSE chunks to the HTTP stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel

from .chunks import ChatChunk, ChunkType


class EventEmitter:
    """One emitter per in-flight request. Stages call ``emit``; the route consumes ``stream``."""

    _SENTINEL: None = None

    def __init__(
        self,
        conversation_id: str,
        on_emit: Callable[[ChatChunk], Any] | None = None,
    ) -> None:
        self._queue: asyncio.Queue[ChatChunk | None] = asyncio.Queue()
        self._conversation_id = conversation_id
        self._closed = False
        # Optional sync side-effect for each emitted chunk (e.g. append to the
        # conversation's replay buffer). Kept sync + in-process to avoid adding
        # latency to the streaming hot path.
        self._on_emit = on_emit

    async def emit(self, chunk_type: ChunkType, data: BaseModel | dict[str, object]) -> None:
        if self._closed:
            return
        chunk = ChatChunk(type=chunk_type, data=data, conversation_id=self._conversation_id)
        if self._on_emit is not None:
            try:
                self._on_emit(chunk)
            except Exception:  # noqa: BLE001 — side-effect must not break the stream.
                pass
        await self._queue.put(chunk)

    async def close(self) -> None:
        """Signal end-of-stream. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        await self._queue.put(self._SENTINEL)

    async def stream(self) -> AsyncIterator[str]:
        """Yield raw JSON payload strings. ``EventSourceResponse`` frames each as
        ``data: <payload>\\n\\n``. Terminates with the literal ``[DONE]`` sentinel
        (which the response wrapper will send as ``data: [DONE]\\n\\n``).
        """
        while True:
            event = await self._queue.get()
            if event is None:
                yield "[DONE]"
                return
            yield event.to_json()
