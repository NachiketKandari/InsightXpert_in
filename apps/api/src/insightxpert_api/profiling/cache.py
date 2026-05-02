"""Process-level memo for DatabaseProfile loads.

The profile bytes don't change between writes, and writes go through a
small, well-known set of routes that can invalidate the cache explicitly.
So a process-local dict-of-`(db_id, profile_kind)` is correct: cache hits
are O(1) and free of DB round-trips; misses fall back to the loader; an
asyncio singleflight prevents duplicate concurrent loads of the same key.

Process-local means each API replica has its own copy. With one or two
replicas and infrequent profile writes that's the right tradeoff. If we
later scale to many replicas with frequent writes, swap this for a
Redis-backed cache — the public API would not need to change.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, Callable

LoaderSync = Callable[[str, str], Any]
LoaderAsync = Callable[[str, str], Awaitable[Any]]

_MISSING = object()


class ProfileCache:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()
        self._aio_locks: dict[tuple[str, str], asyncio.Lock] = {}

    def get(self, db_id: str, profile_kind: str, loader: LoaderSync) -> Any:
        key = (db_id, profile_kind)
        with self._lock:
            cached = self._data.get(key, _MISSING)
        if cached is not _MISSING:
            return cached
        value = loader(db_id, profile_kind)
        if value is None:
            # Don't memoize misses — a later write would not be reflected.
            return None
        with self._lock:
            self._data[key] = value
        return value

    async def aget(self, db_id: str, profile_kind: str, loader: LoaderAsync) -> Any:
        key = (db_id, profile_kind)
        with self._lock:
            cached = self._data.get(key, _MISSING)
            if cached is not _MISSING:
                return cached
            lock = self._aio_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._aio_locks[key] = lock
        async with lock:
            with self._lock:
                cached = self._data.get(key, _MISSING)
            if cached is not _MISSING:
                return cached
            value = await loader(db_id, profile_kind)
            if value is None:
                return None
            with self._lock:
                self._data[key] = value
            return value

    def invalidate(self, db_id: str, profile_kind: str) -> None:
        key = (db_id, profile_kind)
        with self._lock:
            self._data.pop(key, None)
            self._aio_locks.pop(key, None)

    def clear(self) -> None:
        """Test hook only."""
        with self._lock:
            self._data.clear()
            self._aio_locks.clear()


_PROCESS_CACHE = ProfileCache()


def get_process_profile_cache() -> ProfileCache:
    return _PROCESS_CACHE
