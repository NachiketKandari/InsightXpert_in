"""30s TTL in-process cache for /admin/overview aggregates.

Deliberately tiny: single dict keyed by string, no eviction beyond TTL. The
overview payload is ~200 bytes so we don't need bounds. Tests monkeypatch
:data:`_cache` or the ``compute`` callable to prove hits/misses.
"""

from __future__ import annotations

import time
from typing import Any, Callable

TTL_SECONDS = 30

_cache: dict[str, tuple[Any, float]] = {}


def get_or_compute(key: str, compute: Callable[[], Any]) -> Any:
    """Return a cached value if still fresh, else recompute and store."""
    now = time.time()
    hit = _cache.get(key)
    if hit is not None and (now - hit[1]) < TTL_SECONDS:
        return hit[0]
    value = compute()
    _cache[key] = (value, now)
    return value


def clear() -> None:
    """Test helper: wipe the cache between tests."""
    _cache.clear()
