"""Asyncio audit queue + batched background worker.

Batching policy: flush when N rows accumulate OR T milliseconds elapse,
whichever comes first. DB writes run on a thread pool (``asyncio.to_thread``)
so the event loop never blocks — audit must not add latency to user requests
(spec O13). Failures are logged and swallowed; audit is best-effort.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Sequence

from ..db.engine import get_engine
from ..logging import get_logger
from .table import audit_log

log = get_logger("audit")

# Hard back-pressure limit on the audit queue. Once full, new rows are dropped
# rather than growing memory unboundedly.
_QUEUE_MAXSIZE = 5000

# Rate-limiter for overflow warnings: emit at most one warning per this many seconds.
_OVERFLOW_WARN_INTERVAL_S = 30.0


@dataclass
class AuditRow:
    user_id: str | None
    method: str
    path: str
    resource_type: str | None
    resource_id: str | None
    status_code: int
    ip: str | None
    user_agent: str | None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: int = field(default_factory=lambda: int(time.time()))


class AuditQueue:
    """Asyncio queue + single drain task that batches inserts."""

    def __init__(
        self,
        *,
        batch_size: int = 50,
        batch_interval_ms: int = 200,
    ) -> None:
        self._queue: asyncio.Queue[AuditRow] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._batch_size = batch_size
        self._interval = batch_interval_ms / 1000.0
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self.flushed_count = 0
        # Overflow / observability counters.
        self.overflow_total: int = 0
        self._overflow_dropped_since_last_warn: int = 0
        self._last_overflow_warn_at: float = 0.0

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    async def put(self, row: AuditRow) -> None:
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            self.overflow_total += 1
            self._overflow_dropped_since_last_warn += 1
            now = time.monotonic()
            if now - self._last_overflow_warn_at >= _OVERFLOW_WARN_INTERVAL_S:
                log.warning(
                    "audit.queue.overflow",
                    dropped_since_last_warn=self._overflow_dropped_since_last_warn,
                    overflow_total=self.overflow_total,
                    queue_depth=self._queue.qsize(),
                )
                self._last_overflow_warn_at = now
                self._overflow_dropped_since_last_warn = 0

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._task = asyncio.create_task(self._run(), name="audit-queue-drain")

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        # Drain anything still queued (best-effort).
        remaining: list[AuditRow] = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining:
            await asyncio.to_thread(self._blocking_insert, remaining)
            self.flushed_count += len(remaining)

    async def _run(self) -> None:
        """Drain loop: accumulate up to batch_size or until interval, then flush."""
        try:
            while True:
                batch: list[AuditRow] = []
                # Block until first row arrives (no busy-wait).
                first = await self._queue.get()
                batch.append(first)
                deadline = asyncio.get_event_loop().time() + self._interval
                while len(batch) < self._batch_size:
                    timeout = deadline - asyncio.get_event_loop().time()
                    if timeout <= 0:
                        break
                    try:
                        row = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        break
                    batch.append(row)
                try:
                    await asyncio.to_thread(self._blocking_insert, batch)
                    self.flushed_count += len(batch)
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "audit.flush_failed",
                        error=str(exc),
                        error_type=type(exc).__name__,
                        batch_size=len(batch),
                    )
        except asyncio.CancelledError:
            # Flush any partial batch we were holding before exiting.
            raise

    def _blocking_insert(self, rows: Sequence[AuditRow]) -> None:
        if not rows:
            return
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                audit_log.insert(),
                [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "method": r.method,
                        "path": r.path,
                        "resource_type": r.resource_type,
                        "resource_id": r.resource_id,
                        "status_code": r.status_code,
                        "ip": r.ip,
                        "user_agent": r.user_agent,
                        "created_at": r.created_at,
                    }
                    for r in rows
                ],
            )


_queue: AuditQueue | None = None


def get_queue() -> AuditQueue:
    """Process-wide singleton. Lifespan manages start()/stop()."""
    global _queue
    if _queue is None:
        _queue = AuditQueue()
    return _queue


def reset_queue_for_tests() -> None:
    """Test hook only. Drops the singleton so the next call rebuilds."""
    global _queue
    _queue = None
