"""ProfilerStage — runs (or loads cached) ``DatabaseProfile`` for ``ctx.state["db_id"]``.

The vendored ``Profiler`` class is BIRD-benchmark-aware (hard-coded ``Databases/`` +
``profiles/`` paths, BIRD-metadata loading). For v1 we need a path-agnostic profiler
that works over arbitrary SQLite files resolved by ``DatabaseService``. Rather than
mutate the vendored tree, we compose the vendored primitives directly here:

    SchemaExtractor → StatsCollector → (optional) SummaryGenerator

LSH / vector / quirk-enrichment passes are intentionally skipped in v1; downstream
stages handle ``None`` for those indexes. The linker uses LSH only if we pass one
in, so this simplification is safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..services.database_service import DatabaseService
from ..services.profile_service import ProfileService
from ..sse.chunks import ChunkType, ProfileLoadedPayload
from ..vendored.pipeline_core.db import SQLiteDatabase
from ..vendored.pipeline_core.models.profile import DatabaseProfile
from ..vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor
from ..vendored.pipeline_core.profiler.stats_collector import StatsCollector
from .stage import PipelineContext

if TYPE_CHECKING:
    from ..llm.base import BaseLLM


async def build_profile(
    db_id: str,
    db_path: str,
    llm: "BaseLLM | None" = None,
) -> DatabaseProfile:
    """Run the minimal 2-step profiler (schema → stats) against a local SQLite file.

    ``llm`` is accepted for forward-compat but unused in v1: summary/quirk LLM passes
    are skipped because they add latency and require the vendored prompts. Stages
    downstream work fine with empty short/long summaries.
    """
    path = Path(db_path)
    db = SQLiteDatabase(path)
    # Override db_id so schema.db_id matches the logical id the user supplied
    db.db_id = db_id
    with db:
        schema = SchemaExtractor().extract(db)
        profile = StatsCollector(fast=False).collect(db, schema)
    # profile.db_id defaults to schema.db_id (set by StatsCollector) → ensure match
    return profile


class ProfilerStage:
    """Pipeline stage: resolve ``db_id`` → load-or-build profile → cache + emit SSE."""

    name = "profiler"

    def __init__(
        self,
        db_svc: DatabaseService,
        prof_svc: ProfileService,
        llm: "BaseLLM | None" = None,
    ) -> None:
        self._db = db_svc
        self._prof = prof_svc
        self._llm = llm

    async def run(self, ctx: PipelineContext, _: object) -> DatabaseProfile:
        db_id = ctx.state["db_id"]
        ref = self._db.resolve(ctx.session_id, db_id)
        if ref is None:
            raise ValueError(f"database not found: {db_id}")

        cached = self._prof.load(ctx.session_id, db_id)
        if cached is not None:
            ctx.state["profile"] = cached
            await self._emit(ctx, db_id, cached, from_cache=True)
            return cached

        profile = await build_profile(db_id, ref.local_path, llm=self._llm)
        self._prof.save(ctx.session_id, db_id, profile)
        ctx.state["profile"] = profile
        await self._emit(ctx, db_id, profile, from_cache=False)
        return profile

    @staticmethod
    async def _emit(
        ctx: PipelineContext, db_id: str, profile: DatabaseProfile, *, from_cache: bool
    ) -> None:
        if ctx.emitter is None:
            return
        table_count = len(profile.tables)
        column_count = sum(len(t.columns) for t in profile.tables)
        await ctx.emitter.emit(
            ChunkType.PROFILE_LOADED,
            ProfileLoadedPayload(
                db_id=db_id,
                table_count=table_count,
                column_count=column_count,
                from_cache=from_cache,
            ),
        )
