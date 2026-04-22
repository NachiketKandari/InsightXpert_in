"""SSE-streaming profile runner.

Drives the 6 profiling stages (schema, stats, summaries, quirks, lsh, vectors)
and emits ``profile_stage_started`` / ``profile_stage_completed`` chunks on
the standard ``EventEmitter`` so the FE can render stepped progress.

Cost-gate handshake:
  1. FE POSTs with ``confirmed=false`` and the feature flags on. The runner
     emits a single ``profile_cost_estimate`` chunk with ``total_llm_calls`` +
     ``estimated_seconds`` and the stream closes. FE renders a confirmation.
  2. FE re-POSTs with ``confirmed=true`` (same flags). The runner executes
     every stage and emits stage-start/stage-complete + ``profile_done``.

The ``profiling_max_columns_for_llm`` safety cap force-disables all 4
expensive flags when the column count exceeds the threshold — a
``profile.stage_auto_disabled`` warning explains the override.

Cost-estimate formula (documented for parity with the FE)::

    calls_for_summaries = ceil(columns / batch_size) if with_summaries else 0
    calls_for_quirks    = ceil(columns / batch_size) if with_quirks    else 0
    total_llm_calls     = calls_for_summaries + calls_for_quirks
    estimated_seconds   = max(10, total_llm_calls * 2)  # flash ~2s/call, floor 10s
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..logging import get_logger
from ..sse.chunks import (
    ChunkType,
    ProfileDonePayload,
    ProfileErrorPayload,
    ProfileLoadedPayload,
    ProfileProgressPayload,
    ProfileStageCompletedPayload,
    ProfileStageStartedPayload,
)
from ..sse.emitter import EventEmitter
from ..vendored.pipeline_core.db import SQLiteDatabase
from ..vendored.pipeline_core.models.profile import DatabaseProfile
from ..vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor
from ..vendored.pipeline_core.profiler.stats_collector import StatsCollector

if TYPE_CHECKING:  # pragma: no cover
    from ..vendored.pipeline_core.models.schema import DatabaseSchema

log = get_logger("profiling.runner")

# Stage order the FE renders. Keep stable — the FE progress bar depends on
# this ordering. "mechanical" covers schema + stats together.
STAGE_ORDER: tuple[str, ...] = (
    "schema",
    "stats",
    "summaries",
    "quirks",
    "lsh",
    "vectors",
)


@dataclass(frozen=True)
class ProfileFlags:
    """Which optional stages to run after schema+stats."""

    with_summaries: bool = False
    with_quirks: bool = False
    with_lsh: bool = False
    with_vectors: bool = False

    @property
    def any_llm(self) -> bool:
        return self.with_summaries or self.with_quirks

    @property
    def any(self) -> bool:
        return (
            self.with_summaries
            or self.with_quirks
            or self.with_lsh
            or self.with_vectors
        )


@dataclass
class CostEstimate:
    columns: int
    batch_size: int
    total_llm_calls: int
    estimated_seconds: int


def estimate_cost(
    columns: int,
    flags: ProfileFlags,
    batch_size: int,
) -> CostEstimate:
    """Pure function — used by the cost-gate and the estimate route."""
    bs = max(1, batch_size)
    calls_summaries = math.ceil(columns / bs) if flags.with_summaries else 0
    calls_quirks = math.ceil(columns / bs) if flags.with_quirks else 0
    total = calls_summaries + calls_quirks
    # Flash ~2s per call; floor 10s so the confirmation modal never says "0s".
    seconds = max(10, total * 2)
    return CostEstimate(
        columns=columns,
        batch_size=bs,
        total_llm_calls=total,
        estimated_seconds=seconds,
    )


# ---------------------------------------------------------------------------
# Column-count helper — used by the cost-gate route before running the full
# pipeline. Cheap: schema extract only (no stats).
# ---------------------------------------------------------------------------


def count_columns(db_path: str, db_id: str) -> tuple[int, int]:
    """Return ``(table_count, column_count)`` for a SQLite file.

    Uses the vendored ``SchemaExtractor`` so the count matches exactly what
    the profiler will see.
    """
    db = SQLiteDatabase(Path(db_path))
    db.db_id = db_id
    with db:
        schema = SchemaExtractor().extract(db)
    tables = len(schema.tables)
    cols = sum(len(t.columns) for t in schema.tables)
    return tables, cols


# ---------------------------------------------------------------------------
# Streaming run
# ---------------------------------------------------------------------------


async def _emit_stage_started(
    emitter: EventEmitter, stage: str, db_id: str
) -> None:
    log.info("profiling.stage_started", stage=stage, db_id=db_id)
    await emitter.emit(
        ChunkType.profile_stage_started,
        ProfileStageStartedPayload(stage=stage, db_id=db_id),
    )


async def _emit_stage_completed(
    emitter: EventEmitter,
    stage: str,
    db_id: str,
    *,
    duration_ms: int,
    note: str | None = None,
) -> None:
    log.info(
        "profiling.stage_completed",
        stage=stage,
        db_id=db_id,
        duration_ms=duration_ms,
    )
    await emitter.emit(
        ChunkType.profile_stage_completed,
        ProfileStageCompletedPayload(
            stage=stage, db_id=db_id, duration_ms=duration_ms, note=note
        ),
    )


async def _emit_progress(
    emitter: EventEmitter,
    stage: str,
    batch_index: int,
    batch_total: int,
) -> None:
    await emitter.emit(
        ChunkType.profile_progress,
        ProfileProgressPayload(
            stage=stage, batch_index=batch_index, batch_total=batch_total
        ),
    )


async def run_profile_stream(
    emitter: EventEmitter,
    db_id: str,
    db_path: str,
    flags: ProfileFlags,
    *,
    llm: object | None,
    batch_size: int,
    max_columns_for_llm: int,
    batch_disabled: bool = False,
) -> DatabaseProfile | None:
    """Run the full profile pipeline with per-stage SSE emissions.

    Returns the final ``DatabaseProfile`` on success; ``None`` on error
    (``profile_error`` is emitted before returning).
    """
    import time as _time

    try:
        path = Path(db_path)
        db = SQLiteDatabase(path)
        db.db_id = db_id
        with db:
            # --- stage: schema -----------------------------------------
            t0 = _time.perf_counter()
            await _emit_stage_started(emitter, "schema", db_id)
            schema = SchemaExtractor().extract(db)
            schema_ms = int((_time.perf_counter() - t0) * 1000)
            await _emit_stage_completed(
                emitter, "schema", db_id, duration_ms=schema_ms
            )

            all_columns = sum(len(t.columns) for t in schema.tables)

            # --- auto-disable guard ------------------------------------
            effective = flags
            if all_columns > max_columns_for_llm and effective.any:
                log.warning(
                    "profiling.stage_auto_disabled",
                    db_id=db_id,
                    columns=all_columns,
                    threshold=max_columns_for_llm,
                )
                effective = ProfileFlags()  # all off

            # --- stage: stats ------------------------------------------
            t0 = _time.perf_counter()
            await _emit_stage_started(emitter, "stats", db_id)
            profile = StatsCollector(fast=False).collect(db, schema)
            stats_ms = int((_time.perf_counter() - t0) * 1000)
            await _emit_stage_completed(
                emitter, "stats", db_id, duration_ms=stats_ms
            )

            # --- stage: summaries --------------------------------------
            profile = await _maybe_run_summaries(
                emitter=emitter,
                db_id=db_id,
                schema=schema,
                profile=profile,
                run=effective.with_summaries,
                llm=llm,
                batch_size=batch_size,
                batch_disabled=batch_disabled,
            )

            # --- stage: quirks -----------------------------------------
            profile = await _maybe_run_quirks(
                emitter=emitter,
                db_id=db_id,
                schema=schema,
                profile=profile,
                run=effective.with_quirks,
                llm=llm,
                batch_size=batch_size,
                batch_disabled=batch_disabled,
            )

            # --- stage: lsh --------------------------------------------
            await _maybe_run_lsh(
                emitter=emitter,
                db_id=db_id,
                schema=schema,
                db=db,
                run=effective.with_lsh,
            )

            # --- stage: vectors ----------------------------------------
            await _maybe_run_vectors(
                emitter=emitter,
                db_id=db_id,
                profile=profile,
                run=effective.with_vectors,
                llm=llm,
            )

            # --- final done -------------------------------------------
            await emitter.emit(
                ChunkType.profile_done,
                ProfileDonePayload(
                    db_id=db_id,
                    table_count=len(profile.tables),
                    column_count=all_columns,
                    summaries_populated=sum(
                        1
                        for t in profile.tables
                        for c in t.columns
                        if c.short_summary
                    ),
                ),
            )
            return profile

    except asyncio.CancelledError:
        # Client disconnected mid-run. Re-raise so FastAPI / starlette can
        # tear down cleanly instead of logging this as a real error (MF-PR-5).
        log.info("profiling.run_cancelled", db_id=db_id)
        raise
    except Exception as exc:
        log.error(
            "profiling.run_failed",
            db_id=db_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        await emitter.emit(
            ChunkType.profile_error,
            ProfileErrorPayload(db_id=db_id, message=str(exc)),
        )
        return None


# ---------------------------------------------------------------------------
# Stage helpers — keep the main loop readable + skip cleanly when the flag
# is off.
# ---------------------------------------------------------------------------


async def _maybe_run_summaries(
    *,
    emitter: EventEmitter,
    db_id: str,
    schema: DatabaseSchema,
    profile: DatabaseProfile,
    run: bool,
    llm: object | None,
    batch_size: int,
    batch_disabled: bool,
) -> DatabaseProfile:
    import time as _time

    if not run or llm is None:
        await _emit_stage_started(emitter, "summaries", db_id)
        await _emit_stage_completed(
            emitter, "summaries", db_id, duration_ms=0, note="skipped"
        )
        return profile

    t0 = _time.perf_counter()
    await _emit_stage_started(emitter, "summaries", db_id)
    if batch_disabled:
        from ..vendored.pipeline_core.profiler.summary_generator import (
            SummaryGenerator,
        )

        profile = await SummaryGenerator(llm).async_generate(schema, profile)
    else:
        from .batched_summary import BatchedSummaryGenerator

        profile = await BatchedSummaryGenerator(
            llm, batch_size=batch_size
        ).async_generate(schema, profile)
    await _emit_stage_completed(
        emitter,
        "summaries",
        db_id,
        duration_ms=int((_time.perf_counter() - t0) * 1000),
    )
    return profile


async def _maybe_run_quirks(
    *,
    emitter: EventEmitter,
    db_id: str,
    schema: DatabaseSchema,
    profile: DatabaseProfile,
    run: bool,
    llm: object | None,
    batch_size: int,
    batch_disabled: bool,
) -> DatabaseProfile:
    import time as _time

    if not run or llm is None:
        await _emit_stage_started(emitter, "quirks", db_id)
        await _emit_stage_completed(
            emitter, "quirks", db_id, duration_ms=0, note="skipped"
        )
        return profile

    t0 = _time.perf_counter()
    await _emit_stage_started(emitter, "quirks", db_id)
    if batch_disabled:
        from ..vendored.pipeline_core.profiler.quirk_detector import QuirkEnricher

        profile, _calls = await QuirkEnricher(llm).async_enrich(profile, schema)
    else:
        from .batched_quirks import BatchedQuirkDetector

        profile = await BatchedQuirkDetector(
            llm, batch_size=batch_size
        ).async_enrich(profile, schema)
    await _emit_stage_completed(
        emitter,
        "quirks",
        db_id,
        duration_ms=int((_time.perf_counter() - t0) * 1000),
    )
    return profile


async def _maybe_run_lsh(
    *,
    emitter: EventEmitter,
    db_id: str,
    schema: DatabaseSchema,
    db: SQLiteDatabase,
    run: bool,
) -> None:
    import time as _time

    if not run:
        await _emit_stage_started(emitter, "lsh", db_id)
        await _emit_stage_completed(
            emitter, "lsh", db_id, duration_ms=0, note="skipped"
        )
        return
    t0 = _time.perf_counter()
    await _emit_stage_started(emitter, "lsh", db_id)
    from ..vendored.pipeline_core.profiler.lsh_builder import LSHBuilder

    # LSHBuilder is CPU-bound; running inline is fine for v1.
    LSHBuilder().build(db, schema)
    await _emit_stage_completed(
        emitter,
        "lsh",
        db_id,
        duration_ms=int((_time.perf_counter() - t0) * 1000),
    )


async def _maybe_run_vectors(
    *,
    emitter: EventEmitter,
    db_id: str,
    profile: DatabaseProfile,
    run: bool,
    llm: object | None,
) -> None:
    import time as _time

    if not run or llm is None:
        await _emit_stage_started(emitter, "vectors", db_id)
        await _emit_stage_completed(
            emitter, "vectors", db_id, duration_ms=0, note="skipped"
        )
        return
    t0 = _time.perf_counter()
    await _emit_stage_started(emitter, "vectors", db_id)
    from ..vendored.pipeline_core.profiler.vector_builder import VectorBuilder

    await VectorBuilder().async_build(profile, llm)  # type: ignore[arg-type]
    await _emit_stage_completed(
        emitter,
        "vectors",
        db_id,
        duration_ms=int((_time.perf_counter() - t0) * 1000),
    )


# ---------------------------------------------------------------------------
# Legacy-compat helper — the existing ``profile_loaded`` chunk (Tier-3, used
# by chat) is still emitted by ``ProfilerStage``. The new chunks above are
# *additional*, used by the dedicated profile route. Kept separate so the
# chat path keeps its single ``profile_loaded`` surface.
# ---------------------------------------------------------------------------


async def emit_legacy_profile_loaded(
    emitter: EventEmitter,
    db_id: str,
    profile: DatabaseProfile,
    *,
    from_cache: bool,
) -> None:
    await emitter.emit(
        ChunkType.PROFILE_LOADED,
        ProfileLoadedPayload(
            db_id=db_id,
            table_count=len(profile.tables),
            column_count=sum(len(t.columns) for t in profile.tables),
            from_cache=from_cache,
        ),
    )


__all__ = [
    "STAGE_ORDER",
    "CostEstimate",
    "ProfileFlags",
    "count_columns",
    "emit_legacy_profile_loaded",
    "estimate_cost",
    "run_profile_stream",
]
