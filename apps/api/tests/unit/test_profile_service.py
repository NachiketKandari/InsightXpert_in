"""Unit tests for ``ProfileService`` — key derivation + save/load roundtrip."""
from __future__ import annotations

from insightxpert_api.services.profile_service import ProfileService
from insightxpert_api.storage.local import LocalStorage
from insightxpert_api.vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnStats,
    DatabaseProfile,
    TableProfile,
)


def _fake_profile(db_id: str = "demo") -> DatabaseProfile:
    return DatabaseProfile(
        db_id=db_id,
        tables=[
            TableProfile(
                name="t1",
                row_count=3,
                columns=[
                    ColumnProfile(
                        name="c1",
                        type="INTEGER",
                        stats=ColumnStats(count=3, null_count=0, distinct_count=3),
                    ),
                ],
            ),
        ],
    )


def test_profile_service_key_shape(tmp_path) -> None:
    svc = ProfileService(LocalStorage(str(tmp_path)))
    assert svc.key("s1", "demo") == "sessions/s1/profiles/demo/profile.json"


def test_profile_service_roundtrip(tmp_path) -> None:
    store = LocalStorage(str(tmp_path))
    svc = ProfileService(store)
    profile = _fake_profile()

    assert not svc.exists("s1", "demo")
    assert svc.load("s1", "demo") is None

    svc.save("s1", "demo", profile)

    assert svc.exists("s1", "demo")
    loaded = svc.load("s1", "demo")
    assert loaded is not None
    assert loaded.db_id == "demo"
    assert loaded.tables[0].columns[0].name == "c1"


def test_profile_service_isolates_by_session(tmp_path) -> None:
    store = LocalStorage(str(tmp_path))
    svc = ProfileService(store)
    svc.save("alice", "demo", _fake_profile())
    assert svc.exists("alice", "demo")
    assert not svc.exists("bob", "demo")
