"""Async event emitter used by pipeline stages to push SSE chunks to the HTTP stream."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel

from .chunks import ChatChunk, ChunkType

# Queue capacity per emitter — oldest event dropped when full to prevent
# unbounded memory growth for slow / disconnected consumers.
_QUEUE_MAXSIZE = 256

# Drop-log sampling: log at most once every N drops to avoid spam.
_DROP_LOG_SAMPLE = 10


class EventEmitter:
    """One emitter per in-flight request. Stages call ``emit``; the route consumes ``stream``."""

    _SENTINEL: None = None

    def __init__(
        self,
        conversation_id: str,
        on_emit: Callable[[ChatChunk], Any] | None = None,
        user_id: str | None = None,
    ) -> None:
        self._queue: asyncio.Queue[ChatChunk | None] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._conversation_id = conversation_id
        self._closed = False
        self._user_id = user_id
        # Optional sync side-effect for each emitted chunk (e.g. append to the
        # conversation's replay buffer). Kept sync + in-process to avoid adding
        # latency to the streaming hot path.
        self._on_emit = on_emit
        # Track last activity for idle-reaper eviction.
        self.last_activity_at: float = time.monotonic()
        # Count of active consumers (subscribers).
        self._subscriber_count: int = 0
        # Internal drop counter for sampling.
        self._drop_count: int = 0

    @property
    def has_subscriber(self) -> bool:
        return self._subscriber_count > 0

    def _touch(self) -> None:
        """Update last_activity_at to now."""
        self.last_activity_at = time.monotonic()

    async def emit(self, chunk_type: ChunkType, data: BaseModel | dict[str, object]) -> None:
        if self._closed:
            return
        chunk = ChatChunk(type=chunk_type, data=data, conversation_id=self._conversation_id)
        if self._on_emit is not None:
            try:
                self._on_emit(chunk)
            except Exception:  # noqa: BLE001 — side-effect must not break the stream.
                pass
        self._touch()
        if self._queue.full():
            # Drop oldest to make room; log sampled warnings.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._drop_count += 1
            if self._drop_count % _DROP_LOG_SAMPLE == 1:
                # Import here to avoid circular import; logger is lightweight.
                from ..logging import get_logger
                get_logger("sse.emitter").warning(
                    "sse.emitter.queue_full_drop",
                    user_id=self._user_id,
                    conversation_id=self._conversation_id,
                    total_drops=self._drop_count,
                )
        self._queue.put_nowait(chunk)

    async def close(self) -> None:
        """Signal end-of-stream. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        self._touch()
        try:
            self._queue.put_nowait(self._SENTINEL)
        except asyncio.QueueFull:
            # Queue is full; drop oldest and put sentinel to ensure close propagates.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(self._SENTINEL)

    async def stream(self) -> AsyncIterator[str]:
        """Yield raw JSON payload strings. ``EventSourceResponse`` frames each as
        ``data: <payload>\\n\\n``. Terminates with the literal ``[DONE]`` sentinel
        (which the response wrapper will send as ``data: [DONE]\\n\\n``).
        """
        self._subscriber_count += 1
        try:
            while True:
                self._touch()
                event = await self._queue.get()
                if event is None:
                    yield "[DONE]"
                    return
                yield event.to_json()
        finally:
            self._subscriber_count -= 1
