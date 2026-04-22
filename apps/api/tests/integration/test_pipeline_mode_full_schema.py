"""Integration tests for Tier-1 full-schema pipeline mode.

Covers the three-level precedence (request override → per-DB default →
system default ``"linked"``) plus the admin-only gate on the request
override.

The tests rely on monkeypatching ``default_pipeline`` to capture which
``pipeline_mode`` kwarg the chat route resolved, rather than driving a real
Gemini call. This is the same pattern used by ``test_chat_variants.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from insightxpert_api.databases import repository as databases_repo
from insightxpert_api.pipeline.pipeline import Pipeline
from insightxpert_api.pipeline.stage import PipelineContext
from insightxpert_api.sse.chunks import (
    AnswerGeneratedPayload,
    ChunkType,
    SQLGeneratedPayload,
    StatusPayload,
)


class _FakeGen:
    name = "sql_generator"

    async def run(self, ctx: PipelineContext, _: Any) -> str:
        sql = "SELECT 1 AS n"
        if ctx.emitter is not None:
            await ctx.emitter.emit(ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=sql))
        ctx.state["sql"] = sql
        return sql


class _FakeExec:
    name = "sql_executor"

    async def run(self, ctx: PipelineContext, _: Any) -> None:
        if ctx.emitter is not None:
            await ctx.emitter.emit(
                ChunkType.ANSWER_GENERATED,
                AnswerGeneratedPayload(text="ok"),
            )
        ctx.state["rows"] = [[1]]
        ctx.state["answer"] = "ok"
        return None


def _mock_pipeline_capture() -> tuple[list[str], Any]:
    """Return (captured_modes, side_effect_fn).

    Calls to ``default_pipeline`` append the ``pipeline_mode`` kwarg they
    received into ``captured_modes``. The returned pipeline is a 2-stage
    fake that emits the minimum chunks a chat turn needs.
    """
    captured: list[str] = []

    def side_effect(_s, _db, _pf, *, pipeline_mode: str = "linked"):
        captured.append(pipeline_mode)
        return Pipeline([_FakeGen(), _FakeExec()])

    return captured, side_effect


def test_admin_override_to_full_schema_threads_mode(admin_client):
    client, _ = admin_client
    captured, side_effect = _mock_pipeline_capture()
    with patch(
        "insightxpert_api.routes.chat.default_pipeline", side_effect=side_effect
    ):
        r = client.post(
            "/api/v1/chat/poll",
            json={
                "message": "count rows",
                "db_id": "toxicology",
                "pipeline_mode": "full_schema",
            },
        )
    assert r.status_code == 200, r.text
    assert captured == ["full_schema"]
    # None of the linker-specific chunks should have been emitted.
    types = {c["type"] for c in r.json()["chunks"]}
    assert "schema_linking_started" not in types
    assert "linked_schema_final" not in types


def test_non_admin_override_returns_403(user_client):
    client, _ = user_client
    captured, side_effect = _mock_pipeline_capture()
    with patch(
        "insightxpert_api.routes.chat.default_pipeline", side_effect=side_effect
    ):
        r = client.post(
            "/api/v1/chat/poll",
            json={
                "message": "count rows",
                "db_id": "toxicology",
                "pipeline_mode": "full_schema",
            },
        )
    assert r.status_code == 403
    assert r.json()["detail"] == "pipeline_mode_requires_admin"
    # default_pipeline must not have been called at all.
    assert captured == []


def test_per_db_default_used_when_no_request_override(user_client):
    client, _ = user_client
    # Flip toxicology's per-DB default via the repo (the admin PATCH route
    # is covered separately).
    assert databases_repo.set_pipeline_mode_default("toxicology", "full_schema")

    captured, side_effect = _mock_pipeline_capture()
    with patch(
        "insightxpert_api.routes.chat.default_pipeline", side_effect=side_effect
    ):
        r = client.post(
            "/api/v1/chat/poll",
            json={"message": "count rows", "db_id": "toxicology"},
        )
    assert r.status_code == 200, r.text
    assert captured == ["full_schema"]


def test_system_default_is_linked(user_client):
    client, _ = user_client
    captured, side_effect = _mock_pipeline_capture()
    with patch(
        "insightxpert_api.routes.chat.default_pipeline", side_effect=side_effect
    ):
        r = client.post(
            "/api/v1/chat/poll",
            json={"message": "count rows", "db_id": "toxicology"},
        )
    assert r.status_code == 200, r.text
    assert captured == ["linked"]


# --- Admin PATCH endpoint ---------------------------------------------------


def test_admin_patch_sets_pipeline_mode_default(admin_client):
    client, _ = admin_client
    r = client.patch(
        "/api/v1/admin/databases/toxicology",
        json={"pipeline_mode_default": "full_schema"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "db_id": "toxicology",
        "pipeline_mode_default": "full_schema",
    }
    # Verify via admin list view.
    lst = client.get("/api/v1/admin/databases/").json()
    tox = next(row for row in lst if row["db_id"] == "toxicology")
    assert tox["pipeline_mode_default"] == "full_schema"


def test_admin_patch_clear_override(admin_client):
    client, _ = admin_client
    client.patch(
        "/api/v1/admin/databases/toxicology",
        json={"pipeline_mode_default": "full_schema"},
    )
    r = client.patch(
        "/api/v1/admin/databases/toxicology",
        json={"pipeline_mode_default": None},
    )
    assert r.status_code == 200
    assert r.json()["pipeline_mode_default"] is None


def test_admin_patch_unknown_db_404(admin_client):
    client, _ = admin_client
    r = client.patch(
        "/api/v1/admin/databases/does_not_exist",
        json={"pipeline_mode_default": "linked"},
    )
    assert r.status_code == 404


def test_non_admin_patch_forbidden(user_client):
    client, _ = user_client
    r = client.patch(
        "/api/v1/admin/databases/toxicology",
        json={"pipeline_mode_default": "full_schema"},
    )
    assert r.status_code == 403


# --- FullSchemaStage emits a labelling status chunk ------------------------


def test_full_schema_stage_emits_status_chunk():
    """FullSchemaStage must emit one status chunk so FE can label the run."""
    import asyncio

    from insightxpert_api.pipeline.full_schema_stage import FullSchemaStage
    from insightxpert_api.sse.emitter import EventEmitter
    from insightxpert_api.vendored.pipeline_core.models.profile import (
        ColumnProfile,
        ColumnStats,
        DatabaseProfile,
        TableProfile,
    )

    collected: list = []

    class _FakeDbSvc:
        def resolve(self, _sid, _db_id):
            return None  # unused — test provides ctx.state["schema"] directly

    emitter = EventEmitter("c1", on_emit=collected.append)
    stage = FullSchemaStage(db_svc=_FakeDbSvc())
    profile = DatabaseProfile(
        db_id="toxicology",
        tables=[
            TableProfile(
                name="atom",
                row_count=0,
                columns=[
                    ColumnProfile(
                        name="atom_id",
                        type="TEXT",
                        stats=ColumnStats(count=0, null_count=0, distinct_count=0),
                    )
                ],
            )
        ],
    )
    ctx = PipelineContext(session_id="u1", conversation_id="c1", emitter=emitter)
    ctx.state.update(db_id="toxicology", profile=profile)

    async def _drive():
        # Provide a hand-crafted schema so we don't depend on the real file
        # at test time (the _FakeDbSvc.resolve path isn't exercised).
        from insightxpert_api.vendored.pipeline_core.models.schema import (
            ColumnSchema,
            DatabaseSchema,
            TableSchema,
        )

        ctx.state["schema"] = DatabaseSchema(
            db_id="toxicology",
            tables=[
                TableSchema(
                    name="atom",
                    columns=[ColumnSchema(name="atom_id", type="TEXT")],
                )
            ],
        )
        await stage.run(ctx, None)

    asyncio.run(_drive())
    assert "schema_text" in ctx.state
    status_chunks = [c for c in collected if c.type == ChunkType.STATUS]
    assert len(status_chunks) == 1
    assert "full_schema" in status_chunks[0].data.message.lower()
