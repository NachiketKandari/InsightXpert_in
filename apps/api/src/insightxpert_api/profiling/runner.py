"""SSE-streaming profile runner.

Drives the 7 profiling stages (schema, stats, join_graph, summaries, quirks, lsh, vectors)
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

import asyncio
import math
import os
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
from ..services.database_service import DatabaseRef
from ..sse.emitter import EventEmitter
from ..vendored.pipeline_core.db import Database, SQLiteDatabase
from ..vendored.pipeline_core.models.profile import DatabaseProfile
from ..vendored.pipeline_core.profiler.join_graph_builder import build_join_graph
from ..vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor
from ..vendored.pipeline_core.profiler.stats_collector import StatsCollector

if TYPE_CHECKING:  # pragma: no cover
    from ..vendored.pipeline_core.models.schema import DatabaseSchema

log = get_logger("profiling.runner")

# --------------------------------------------------------------------------
# Phase 1.4 — profile-specific concurrency cap.
# Stricter than the general LLM semaphore (llm/gemini.py). One user running
# a 90-column profile must not block every other user's chat turn. The
# semaphore is module-level + lazy so tests can override via
# ``_reset_profile_semaphore`` below.
# --------------------------------------------------------------------------

_PROFILE_SEMAPHORE: asyncio.Semaphore | None = None


def _profile_semaphore() -> asyncio.Semaphore:
    global _PROFILE_SEMAPHORE
    if _PROFILE_SEMAPHORE is None:
        cap = int(os.environ.get("PROFILE_MAX_CONCURRENCY", "2") or 2)
        _PROFILE_SEMAPHORE = asyncio.Semaphore(max(1, cap))
    return _PROFILE_SEMAPHORE


def _reset_profile_semaphore(n: int) -> None:
    # TEST-ONLY: used by test_profiling_semaphore.py
    """Test hook — reset the module-level profile semaphore."""
    global _PROFILE_SEMAPHORE
    _PROFILE_SEMAPHORE = asyncio.Semaphore(max(1, int(n)))


@dataclass(frozen=True)
class ProfileFlags:
    """Which optional stages to run after schema+stats."""

    with_summaries: bool = False
    with_quirks: bool = False
    with_lsh: bool = False
    with_vectors: bool = False
    with_table_descriptions: bool = False

    @property
    def any_llm(self) -> bool:
        return self.with_summaries or self.with_quirks or self.with_table_descriptions

    @property
    def any(self) -> bool:
        return (
            self.with_summaries
            or self.with_quirks
            or self.with_lsh
            or self.with_vectors
            or self.with_table_descriptions
        )


@dataclass
class CostEstimate:
    columns: int
    batch_size: int
    total_llm_calls: int
    estimated_seconds: int
    provider: str = ""
    model: str = ""


def estimate_cost(
    columns: int,
    flags: ProfileFlags,
    batch_size: int,
    *,
    table_count: int = 0,
    provider: str = "",
    model: str = "",
) -> CostEstimate:
    """Pure function — used by the cost-gate and the estimate route."""
    bs = max(1, batch_size)
    calls_summaries = math.ceil(columns / bs) if flags.with_summaries else 0
    calls_quirks = math.ceil(columns / bs) if flags.with_quirks else 0
    calls_table_descs = table_count if flags.with_table_descriptions else 0
    total = calls_summaries + calls_quirks + calls_table_descs
    # Flash ~2s per call; floor 10s so the confirmation modal never says "0s".
    seconds = max(10, total * 2)
    return CostEstimate(
        columns=columns,
        batch_size=bs,
        total_llm_calls=total,
        estimated_seconds=seconds,
        provider=provider,
        model=model,
    )


# ---------------------------------------------------------------------------
# Dialect helpers — open a vendored Database for either SQLite or Postgres,
# and extract schema using the appropriate extractor.
# ---------------------------------------------------------------------------


def _open_database_for_ref(ref: DatabaseRef) -> Database:
    """Open a vendored ``Database`` for whichever dialect the ref names.

    Pure adapter dispatch — no per-dialect branching here. Add a new dialect
    by registering a `DialectAdapter` with an ``open_database(ref)`` method;
    this call site doesn't change.
    """
    from ..db.dialects import get_adapter

    return get_adapter(ref.dialect).open_database(ref)


def _extract_schema_from_db(ref: DatabaseRef, db: Database):
    """Extract a DatabaseSchema — dispatches to the adapter's extractor.

    ``ref`` flows through so dialect-specific metadata (e.g. pg_schema for
    Postgres) can be consumed by the extractor.
    """
    from ..db.dialects import get_adapter

    return get_adapter(ref.dialect).extract_schema(db, ref)


# ---------------------------------------------------------------------------
# Column-count helper — used by the cost-gate route before running the full
# pipeline. Cheap: schema extract only (no stats).
# ---------------------------------------------------------------------------


def count_columns(ref: DatabaseRef) -> tuple[int, int]:
    """Return ``(table_count, column_count)`` for a DB — dialect-aware.

    Uses the vendored ``SchemaExtractor`` so the count matches exactly what
    the profiler will see.
    """
    db = _open_database_for_ref(ref)
    with db:
        schema = _extract_schema_from_db(ref, db)
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


async def _run_stats_stage(
    emitter: EventEmitter,
    db_id: str,
    db: SQLiteDatabase,
    schema: "DatabaseSchema",
    stage_timings: dict[str, int] | None = None,
) -> "DatabaseProfile":
    """Run the stats stage with SSE emission. Returns the populated profile."""
    import time as _time

    t0 = _time.perf_counter()
    await _emit_stage_started(emitter, "stats", db_id)
    profile = StatsCollector(fast=False).collect(db, schema)
    stats_ms = int((_time.perf_counter() - t0) * 1000)
    if stage_timings is not None:
        stage_timings["stats"] = stats_ms
    await _emit_stage_completed(
        emitter, "stats", db_id, duration_ms=stats_ms
    )
    return profile


async def _run_join_graph_stage(
    emitter: EventEmitter,
    db_id: str,
    schema: "DatabaseSchema",
    db: SQLiteDatabase,
    indices_dir: str = "",
    stage_timings: dict[str, int] | None = None,
) -> None:
    """Run the join graph stage with SSE emission.

    Discovers declared + implicit FKs with value verification.
    Saves ``join_graph.json`` to disk when ``indices_dir`` is provided.
    The route persists it to the database after the run.
    """
    import time as _time

    t0 = _time.perf_counter()
    await _emit_stage_started(emitter, "join_graph", db_id)
    jg = build_join_graph(schema, db)
    if indices_dir:
        jg_dir = Path(indices_dir) / db_id
        jg_dir.mkdir(parents=True, exist_ok=True)
        jg_dir.joinpath("join_graph.json").write_text(jg.model_dump_json(indent=2))
    elapsed_ms = int((_time.perf_counter() - t0) * 1000)
    if stage_timings is not None:
        stage_timings["join_graph"] = elapsed_ms
    edge_count = len(jg.edges)
    declared = sum(1 for e in jg.edges if e.kind == "declared")
    verified = sum(1 for e in jg.edges if e.kind == "value_verified")
    note = f"{edge_count} edges ({declared} declared, {verified} value-verified)"
    await _emit_stage_completed(
        emitter, "join_graph", db_id, duration_ms=elapsed_ms, note=note
    )


def _unwrap_profile(
    result: object,
    db_id: str,
    stage: str,
    *,
    fallback: "DatabaseProfile | None" = None,
    emitter: "EventEmitter | None" = None,
) -> "DatabaseProfile | None":
    """Unpack an ``asyncio.gather`` result for a profile-returning stage.

    On success, returns the ``DatabaseProfile``. On failure, emits a
    ``profile_stage_completed`` chunk with ``note=\"failed: …\"`` so the
    frontend stepper shows the stage as errored (instead of leaving it
    silently stuck in "running"), logs a warning, and returns *fallback*
    so downstream stages can continue.
    """
    if isinstance(result, BaseException):
        log.warning(
            "profiling.stage_failed",
            stage=stage,
            db_id=db_id,
            error=str(result),
            error_type=type(result).__name__,
        )
        if emitter is not None:
            import asyncio as _asyncio

            _asyncio.create_task(
                _emit_stage_completed(
                    emitter,
                    stage,
                    db_id,
                    duration_ms=0,
                    note=f"failed: {type(result).__name__}",
                )
            )
        return fallback
    if isinstance(result, DatabaseProfile):
        return result
    return fallback


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
    indices_dir: str = "",
    # Phase 1.2 + 1.4 — when provided, the runner emits a usage record for
    # every profile run (summaries + quirks LLM batches) tagged with this
    # user. The runner also honours a module-level profile semaphore to cap
    # concurrent LLM-driven profile runs globally.
    user_id: str | None = None,
    provider: str = "gemini",
    model: str | None = None,
    user_hints: str = "",
    ref: DatabaseRef | None = None,
) -> DatabaseProfile | None:
    """Run the full profile pipeline with per-stage SSE emissions.

    Returns the final ``DatabaseProfile`` on success; ``None`` on error
    (``profile_error`` is emitted before returning).
    """
    import json as _json
    import time as _time

    # Snapshot token counters before the run so we can attribute only the
    # delta to this db_id. Wrap the entire run in try/finally so usage fires
    # on success, error, AND cancellation (spend-quota design §3.3).
    tokens_before_in = int(getattr(llm, "input_tokens_used", 0) or 0)
    tokens_before_out = int(getattr(llm, "output_tokens_used", 0) or 0)
    run_start = _time.perf_counter()
    stage_timings: dict[str, int] = {}
    profile = None  # surviving reference for CancelledError path

    # Phase 1.4 — cap concurrent LLM-driven profile runs globally. Only
    # gate when an LLM stage will actually fire; the cheap schema+stats path
    # should never be rate-limited by another user's 90-column profile.
    needs_semaphore = llm is not None and (flags.any_llm or flags.with_vectors)
    sem = _profile_semaphore() if needs_semaphore else None

    if sem is not None:
        await sem.acquire()

    try:
        if ref is not None:
            db = _open_database_for_ref(ref)
        else:
            path = Path(db_path)
            db = SQLiteDatabase(path)
            db.db_id = db_id
        with db:
            # --- Phase 1: schema (sequential prerequisite) ---------------
            t0 = _time.perf_counter()
            await _emit_stage_started(emitter, "schema", db_id)
            if ref is not None:
                schema = _extract_schema_from_db(ref, db)
            else:
                schema = SchemaExtractor().extract(db)
            schema_ms = int((_time.perf_counter() - t0) * 1000)
            stage_timings["schema"] = schema_ms
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

            # --- Phase 2: stats + join_graph (parallel) -------------------
            # Both only need schema + db — fully independent.
            phase2_tasks = [
                _run_stats_stage(emitter, db_id, db, schema, stage_timings=stage_timings),
                _run_join_graph_stage(emitter, db_id, schema, db, indices_dir, stage_timings=stage_timings),
            ]
            phase2_results = await asyncio.gather(
                *phase2_tasks, return_exceptions=True
            )
            profile = _unwrap_profile(phase2_results[0], db_id, "stats", emitter=emitter)

            # --- Phase 3: summaries + quirks + lsh (parallel) -------------
            # summaries and quirks both need the profile (with stats populated).
            # lsh only needs schema + db, so it can run alongside the LLM stages.
            phase3_tasks = [
                _maybe_run_summaries(
                    emitter=emitter, db_id=db_id, schema=schema,
                    profile=profile, run=effective.with_summaries,
                    llm=llm, batch_size=batch_size,
                    batch_disabled=batch_disabled,
                    user_hints=user_hints,
                    stage_timings=stage_timings,
                ),
                _maybe_run_quirks(
                    emitter=emitter, db_id=db_id, schema=schema,
                    profile=profile, run=effective.with_quirks,
                    llm=llm, batch_size=batch_size,
                    batch_disabled=batch_disabled,
                    user_hints=user_hints,
                    stage_timings=stage_timings,
                ),
                _maybe_run_lsh(
                    emitter=emitter, db_id=db_id, schema=schema,
                    db=db, run=effective.with_lsh, indices_dir=indices_dir,
                    stage_timings=stage_timings,
                ),
            ]
            phase3_results = await asyncio.gather(
                *phase3_tasks, return_exceptions=True
            )
            profile = _unwrap_profile(phase3_results[0], db_id, "summaries", fallback=profile, emitter=emitter)
            profile = _unwrap_profile(phase3_results[1], db_id, "quirks", fallback=profile, emitter=emitter)

            # --- Phase 4: vectors (depends on summaries for embed text) ---
            await _maybe_run_vectors(
                emitter=emitter,
                db_id=db_id,
                profile=profile,
                run=effective.with_vectors,
                llm=llm,
                indices_dir=indices_dir,
                stage_timings=stage_timings,
            )

            # --- Phase 5: table descriptions (depends on summaries + quirks) ---
            profile = await _maybe_run_table_descriptions(
                emitter=emitter,
                db_id=db_id,
                profile=profile,
                run=effective.with_table_descriptions,
                llm=llm,
                user_hints=user_hints,
                stage_timings=stage_timings,
            )

            return profile

    except asyncio.CancelledError:
        # Connection closed mid-run. Log and return whatever profile we have
        # so the caller can still persist schema + stats.
        log.info("profiling.run_cancelled", db_id=db_id)
        return profile
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
    finally:
        # Phase 1.4 — release the profile semaphore under all paths.
        if sem is not None:
            try:
                sem.release()
            except (ValueError, RuntimeError):
                pass
        # Phase 1.2 — always emit a usage record for this profile run, even on
        # error or cancel, so quota accounting is accurate (spend-quota §3.3).
        if user_id is not None and llm is not None:
            try:
                from ..metrics.llm_usage import record_llm_usage

                tokens_in = (
                    int(getattr(llm, "input_tokens_used", 0) or 0)
                    - tokens_before_in
                )
                tokens_out = (
                    int(getattr(llm, "output_tokens_used", 0) or 0)
                    - tokens_before_out
                )
                if tokens_in > 0 or tokens_out > 0:
                    duration_ms = int((_time.perf_counter() - run_start) * 1000)
                    record_llm_usage(
                        source="profile",
                        provider=provider,
                        model=model or "gemini-2.5-flash",
                        input_tokens=tokens_in,
                        output_tokens=tokens_out,
                        user_id=user_id,
                        source_ref_id=db_id,
                        db_id=db_id,
                        duration_ms=duration_ms,
                        stage_timings_json=_json.dumps(stage_timings) if stage_timings else None,
                    )
            except Exception:  # noqa: BLE001 — helper already swallows, belt & braces
                pass


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
    user_hints: str = "",
    stage_timings: dict[str, int] | None = None,
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

        profile = await SummaryGenerator(llm).async_generate(
            schema, profile, unified_evidence=user_hints
        )
    else:
        from .batched_summary import BatchedSummaryGenerator

        profile = await BatchedSummaryGenerator(
            llm, batch_size=batch_size
        ).async_generate(schema, profile, unified_evidence=user_hints)
    duration_ms = int((_time.perf_counter() - t0) * 1000)
    if stage_timings is not None:
        stage_timings["summaries"] = duration_ms
    await _emit_stage_completed(
        emitter,
        "summaries",
        db_id,
        duration_ms=duration_ms,
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
    user_hints: str = "",
    stage_timings: dict[str, int] | None = None,
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
        ).async_enrich(profile, schema, unified_evidence=user_hints)
    duration_ms = int((_time.perf_counter() - t0) * 1000)
    if stage_timings is not None:
        stage_timings["quirks"] = duration_ms
    await _emit_stage_completed(
        emitter,
        "quirks",
        db_id,
        duration_ms=duration_ms,
    )
    return profile


async def _maybe_run_lsh(
    *,
    emitter: EventEmitter,
    db_id: str,
    schema: DatabaseSchema,
    db: Database,
    run: bool,
    indices_dir: str = "",
    stage_timings: dict[str, int] | None = None,
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
    lsh_index = LSHBuilder().build(db, schema)
    if indices_dir:
        p = Path(indices_dir) / db_id
        p.mkdir(parents=True, exist_ok=True)
        lsh_index.save(p / "lsh_index.pkl")
    duration_ms = int((_time.perf_counter() - t0) * 1000)
    if stage_timings is not None:
        stage_timings["lsh"] = duration_ms
    await _emit_stage_completed(
        emitter,
        "lsh",
        db_id,
        duration_ms=duration_ms,
    )


async def _maybe_run_vectors(
    *,
    emitter: EventEmitter,
    db_id: str,
    profile: DatabaseProfile,
    run: bool,
    llm: object | None,
    indices_dir: str = "",
    stage_timings: dict[str, int] | None = None,
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

    vec_index = await VectorBuilder().async_build(profile, llm)  # type: ignore[arg-type]
    if indices_dir:
        p = Path(indices_dir) / db_id
        p.mkdir(parents=True, exist_ok=True)
        vec_index.save(p / "vector.npz", p / "vector_columns.json")
    duration_ms = int((_time.perf_counter() - t0) * 1000)
    if stage_timings is not None:
        stage_timings["vectors"] = duration_ms
    await _emit_stage_completed(
        emitter,
        "vectors",
        db_id,
        duration_ms=duration_ms,
    )


async def _maybe_run_table_descriptions(
    *,
    emitter: EventEmitter,
    db_id: str,
    profile: DatabaseProfile,
    run: bool,
    llm: object | None,
    user_hints: str = "",
    stage_timings: dict[str, int] | None = None,
) -> DatabaseProfile:
    import time as _time

    if not run or llm is None:
        await _emit_stage_started(emitter, "table_descriptions", db_id)
        await _emit_stage_completed(
            emitter, "table_descriptions", db_id, duration_ms=0, note="skipped"
        )
        return profile

    t0 = _time.perf_counter()
    await _emit_stage_started(emitter, "table_descriptions", db_id)
    from .table_description import TableDescriptionGenerator

    profile = await TableDescriptionGenerator(llm).async_generate(
        profile, unified_evidence=user_hints
    )
    duration_ms = int((_time.perf_counter() - t0) * 1000)
    if stage_timings is not None:
        stage_timings["table_descriptions"] = duration_ms
    await _emit_stage_completed(
        emitter,
        "table_descriptions",
        db_id,
        duration_ms=duration_ms,
    )
    return profile


__all__ = [
    "CostEstimate",
    "ProfileFlags",
    "count_columns",
    "estimate_cost",
    "run_profile_stream",
]
