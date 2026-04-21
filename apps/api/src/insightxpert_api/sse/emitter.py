"""Async event emitter used by pipeline stages to push SSE chunks to the HTTP stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pydantic import BaseModel

from .chunks import ChatChunk, ChunkType


class EventEmitter:
    """One emitter per in-flight request. Stages call ``emit``; the route consumes ``stream``."""

    _SENTINEL: None = None

    def __init__(self, conversation_id: str) -> None:
        self._queue: asyncio.Queue[ChatChunk | None] = asyncio.Queue()
        self._conversation_id = conversation_id
        self._closed = False

    async def emit(self, chunk_type: ChunkType, data: BaseModel | dict[str, object]) -> None:
        if self._closed:
            return
        chunk = ChatChunk(type=chunk_type, data=data, conversation_id=self._conversation_id)
        await self._queue.put(chunk)

    async def close(self) -> None:
        """Signal end-of-stream. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        await self._queue.put(self._SENTINEL)

    async def stream(self) -> AsyncIterator[str]:
        """Yield SSE frames. Terminates with ``data: [DONE]`` after ``close()``."""
        while True:
            event = await self._queue.get()
            if event is None:
                yield "data: [DONE]\n\n"
                return
            yield event.to_sse()
