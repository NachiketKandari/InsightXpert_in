"""ProfilerStage — runs (or loads cached) ``DatabaseProfile`` for ``ctx.state["db_id"]``.

The vendored ``Profiler`` class is BIRD-benchmark-aware (hard-coded ``Databases/`` +
``profiles/`` paths, BIRD-metadata loading). For v1 we need a path-agnostic profiler
that works over arbitrary SQLite files resolved by ``DatabaseService``. Rather than
mutate the vendored tree, we compose the vendored primitives directly here:

    SchemaExtractor → StatsCollector → (optional) BatchedSummaryGenerator →
      (optional) BatchedQuirkDetector → (optional) LSH → (optional) vectors

Flags on :func:`build_profile` opt-in the expensive LLM / index stages one at a
time. All four auto-disable when the total column count exceeds
``settings.profiling_max_columns_for_llm``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..logging import get_logger
from ..services.database_service import DatabaseService
from ..services.profile_service import ProfileService
from ..sse.chunks import ChunkType, ProfileLoadedPayload
from ..vendored.pipeline_core.db import SQLiteDatabase
from ..vendored.pipeline_core.models.profile import DatabaseProfile
from ..vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor
from ..vendored.pipeline_core.profiler.stats_collector import StatsCollector
from .stage import PipelineContext

if TYPE_CHECKING:
    from ..llm import LLMProvider
    from ..vendored.pipeline_core.models.schema import DatabaseSchema

log = get_logger("pipeline.profiler_stage")


async def build_profile(
    db_id: str,
    db_path: str,
    llm: LLMProvider | None = None,
    *,
    with_summaries: bool = False,
    with_quirks: bool = False,
    with_lsh: bool = False,
    with_vectors: bool = False,
    batch_size: int = 20,
    batch_disabled: bool = False,
    max_columns_for_llm: int = 500,
) -> DatabaseProfile:
    """Run the profiler against a local SQLite file.

    Default (all flags off) reproduces the pre-upgrade behaviour — a fast
    ``schema → stats`` pass with empty summaries. When a flag is on the
    matching stage is invoked via the batched wrapper (or the vendored
    per-column path when ``batch_disabled`` is True).

    The four optional stages **auto-disable** when the total column count
    exceeds ``max_columns_for_llm``; a ``profiler.stage_auto_disabled``
    warning explains the override.
    """
    path = Path(db_path)
    db = SQLiteDatabase(path)
    db.db_id = db_id
    with db:
        schema = SchemaExtractor().extract(db)
        all_columns = sum(len(t.columns) for t in schema.tables)

        # --- auto-disable guard -----------------------------------------
        any_flag = with_summaries or with_quirks or with_lsh or with_vectors
        if any_flag and all_columns > max_columns_for_llm:
            log.warning(
                "profiler.stage_auto_disabled",
                db_id=db_id,
                columns=all_columns,
                threshold=max_columns_for_llm,
            )
            with_summaries = False
            with_quirks = False
            with_lsh = False
            with_vectors = False

        profile = StatsCollector(fast=False).collect(db, schema)

        if with_summaries and llm is not None:
            profile = await _run_summaries(
                schema, profile, llm, batch_size, batch_disabled
            )
        if with_quirks and llm is not None:
            profile = await _run_quirks(
                schema, profile, llm, batch_size, batch_disabled
            )
        if with_lsh:
            _run_lsh(db, schema)
        if with_vectors and llm is not None:
            await _run_vectors(profile, llm)

    return profile


async def _run_summaries(
    schema: DatabaseSchema,
    profile: DatabaseProfile,
    llm: object,
    batch_size: int,
    batch_disabled: bool,
) -> DatabaseProfile:
    if batch_disabled:
        from ..vendored.pipeline_core.profiler.summary_generator import (
            SummaryGenerator,
        )

        return await SummaryGenerator(llm).async_generate(schema, profile)

    from ..profiling.batched_summary import BatchedSummaryGenerator

    return await BatchedSummaryGenerator(
        llm, batch_size=batch_size
    ).async_generate(schema, profile)


async def _run_quirks(
    schema: DatabaseSchema,
    profile: DatabaseProfile,
    llm: object,
    batch_size: int,
    batch_disabled: bool,
) -> DatabaseProfile:
    if batch_disabled:
        from ..vendored.pipeline_core.profiler.quirk_detector import QuirkEnricher

        profile, _calls = await QuirkEnricher(llm).async_enrich(profile, schema)
        return profile

    from ..profiling.batched_quirks import BatchedQuirkDetector

    return await BatchedQuirkDetector(
        llm, batch_size=batch_size
    ).async_enrich(profile, schema)


def _run_lsh(db: SQLiteDatabase, schema: DatabaseSchema) -> None:
    from ..vendored.pipeline_core.profiler.lsh_builder import LSHBuilder

    LSHBuilder().build(db, schema)


async def _run_vectors(profile: DatabaseProfile, llm: object) -> None:
    from ..vendored.pipeline_core.profiler.vector_builder import VectorBuilder

    await VectorBuilder().async_build(profile, llm)  # type: ignore[arg-type]


class ProfilerStage:
    """Pipeline stage: resolve ``db_id`` → load-or-build profile → cache + emit SSE."""

    name = "profiler"

    def __init__(
        self,
        db_svc: DatabaseService,
        prof_svc: ProfileService,
        llm: LLMProvider | None = None,
    ) -> None:
        self._db = db_svc
        self._prof = prof_svc
        self._llm = llm

    async def run(self, ctx: PipelineContext, _: object) -> DatabaseProfile:
        db_id = ctx.state["db_id"]
        ref = self._db.resolve(ctx.session_id, db_id)
        if ref is None:
            raise ValueError(f"database not found: {db_id}")

        # Propagate dialect so downstream stages (validator, generator) can read
        # it from state without needing their own DatabaseService injection.
        ctx.state["db_dialect"] = getattr(ref, "dialect", "sqlite")

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
