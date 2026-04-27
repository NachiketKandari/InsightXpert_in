"""Unit tests for the ``database_profiles`` repository + ProfileService swap.

Verifies the Phase 4b cutover from ObjectStore-blob to a real Postgres table.
"""

from __future__ import annotations

import json
import pytest

from insightxpert_api.profiling import repository as profiles_repo
from insightxpert_api.services.profile_service import ProfileService


def _sample_profile_json() -> str:
    """Minimal-shape JSON that DatabaseProfile.model_validate_json accepts.

    We keep this in the repository test rather than coupling to the model so
    the repo layer stays oblivious to ``DatabaseProfile``.
    """
    return json.dumps({"db_id": "test_db", "tables": []})


def test_upsert_then_get_round_trip(fresh_db):
    profiles_repo.upsert(
        db_id="dbA",
        profile_json='{"x": 1}',
        owner_user_id="u1",
        generated_by="u1",
    )
    row = profiles_repo.get("dbA")
    assert row is not None
    assert row["profile_json"] == '{"x": 1}'
    assert row["owner_user_id"] == "u1"
    assert row["profile_kind"] == "base"
    assert row["generated_at"] > 0


def test_upsert_overwrites_same_kind(fresh_db):
    profiles_repo.upsert(db_id="dbA", profile_json='{"v": 1}')
    profiles_repo.upsert(db_id="dbA", profile_json='{"v": 2}')
    row = profiles_repo.get("dbA")
    assert row["profile_json"] == '{"v": 2}'


def test_upsert_distinct_kinds_coexist(fresh_db):
    profiles_repo.upsert(db_id="dbA", profile_kind="base", profile_json='{"k": "b"}')
    profiles_repo.upsert(db_id="dbA", profile_kind="with_summaries", profile_json='{"k": "s"}')
    base = profiles_repo.get("dbA", "base")
    summ = profiles_repo.get("dbA", "with_summaries")
    assert base["profile_json"] == '{"k": "b"}'
    assert summ["profile_json"] == '{"k": "s"}'


def test_get_returns_none_for_missing(fresh_db):
    assert profiles_repo.get("never_existed") is None


def test_exists(fresh_db):
    assert profiles_repo.exists("dbA") is False
    profiles_repo.upsert(db_id="dbA", profile_json="{}")
    assert profiles_repo.exists("dbA") is True


def test_delete_for_db_drops_all_kinds(fresh_db):
    profiles_repo.upsert(db_id="dbA", profile_kind="base", profile_json="{}")
    profiles_repo.upsert(db_id="dbA", profile_kind="with_summaries", profile_json="{}")
    profiles_repo.upsert(db_id="dbB", profile_kind="base", profile_json="{}")
    n = profiles_repo.delete_for_db("dbA")
    assert n == 2
    assert profiles_repo.get("dbA", "base") is None
    assert profiles_repo.get("dbA", "with_summaries") is None
    assert profiles_repo.get("dbB", "base") is not None  # other db untouched


def test_profile_service_round_trip(fresh_db):
    """End-to-end: ProfileService.save → load reads back equivalent profile."""
    from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile

    profile = DatabaseProfile.model_validate_json(_sample_profile_json())
    svc = ProfileService()  # store arg now optional
    svc.save("user-123", "test_db", profile)

    loaded = svc.load("user-123", "test_db")
    assert loaded is not None
    assert loaded.db_id == "test_db"
    assert svc.exists("user-123", "test_db") is True


def test_profile_service_load_missing(fresh_db):
    svc = ProfileService()
    assert svc.load("any-user", "no_such_db") is None
    assert svc.exists("any-user", "no_such_db") is False
