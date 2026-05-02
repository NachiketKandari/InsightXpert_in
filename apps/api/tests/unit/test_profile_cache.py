"""Process-level profile cache. Hit returns memoized; miss queries DB
and memoizes; invalidate drops the entry; concurrent gets dedupe."""

from __future__ import annotations

import asyncio
import pytest

from insightxpert_api.profiling.cache import ProfileCache


def _fake_profile(name: str):
    """Stand-in for a DatabaseProfile — anything truthy and identifiable."""
    return {"db": name}


def test_hit_returns_memoized_value_without_calling_loader():
    cache = ProfileCache()
    calls = {"n": 0}

    def loader(db_id: str, kind: str):
        calls["n"] += 1
        return _fake_profile(db_id)

    a = cache.get("db1", "base", loader)
    b = cache.get("db1", "base", loader)
    assert a == b == _fake_profile("db1")
    assert calls["n"] == 1


def test_miss_then_hit_short_circuits_after_first_load():
    cache = ProfileCache()
    calls = {"n": 0}

    def loader(db_id: str, kind: str):
        calls["n"] += 1
        return _fake_profile(db_id)

    cache.get("db1", "base", loader)
    cache.get("db2", "base", loader)
    cache.get("db1", "base", loader)
    assert calls["n"] == 2  # one per distinct (db_id, kind)


def test_invalidate_drops_entry():
    cache = ProfileCache()
    calls = {"n": 0}

    def loader(db_id: str, kind: str):
        calls["n"] += 1
        return _fake_profile(db_id)

    cache.get("db1", "base", loader)
    cache.invalidate("db1", "base")
    cache.get("db1", "base", loader)
    assert calls["n"] == 2


def test_invalidate_unknown_key_is_noop():
    cache = ProfileCache()
    cache.invalidate("never_seen", "base")  # must not raise


def test_loader_returning_none_is_not_cached():
    """None means 'no profile in DB'. Caching None would mask later writes."""
    cache = ProfileCache()
    calls = {"n": 0}

    def loader(db_id: str, kind: str):
        calls["n"] += 1
        return None

    assert cache.get("db1", "base", loader) is None
    assert cache.get("db1", "base", loader) is None
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_concurrent_get_dedupes_to_one_loader_call():
    """Two coroutines asking for the same key should issue one DB read."""
    cache = ProfileCache()
    calls = {"n": 0}
    in_flight = asyncio.Event()
    release = asyncio.Event()

    async def loader_async(db_id: str, kind: str):
        calls["n"] += 1
        in_flight.set()
        await release.wait()
        return _fake_profile(db_id)

    async def go():
        return await cache.aget("db1", "base", loader_async)

    t1 = asyncio.create_task(go())
    await in_flight.wait()
    t2 = asyncio.create_task(go())
    # Give t2 a tick to enter the singleflight wait.
    await asyncio.sleep(0.01)
    release.set()
    a, b = await asyncio.gather(t1, t2)
    assert a == b == _fake_profile("db1")
    assert calls["n"] == 1
