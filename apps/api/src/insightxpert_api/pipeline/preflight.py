"""Pre-pipeline preflight: run async-safe, LLM-independent setup concurrently.

Today's pipeline starts sequentially with ``ProfilerStage`` which loads (or
builds) a ``DatabaseProfile`` before the first LLM call (schema linking).
The route layer also frequently runs an LLM-driven mode classifier
(``services.mode_router.classify_mode``) before dispatching the pipeline.

These two operations are independent — the classifier looks only at the
question + db_id, the profile load looks only at the db_id — so we can fire
them concurrently and have the profile sitting warm by the time the pipeline
begins. The pipeline's first LLM call (schema linking) then fires sooner.

Design notes:
  * Profile load is inherently a blocking DB read (``profiles_repo.get`` is
    sync), so we wrap in ``asyncio.to_thread`` to keep the event loop free
    for whatever else is racing alongside it.
  * Failures are swallowed — preflight is an optimisation. If the profile
    isn't there or the load fails, ``ProfilerStage`` will go through its
    normal cold-cache path and surface any real errors.
  * The result is stashed on ``ctx.state["__prefetched_profile"]``; the
    leading underscores mark it as an internal handoff key the route owns.
    ``ProfilerStage`` consumes-and-pops it.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ..logging import get_logger

if TYPE_CHECKING:
    from ..services.profile_service import ProfileService
    from ..vendored.pipeline_core.models.profile import DatabaseProfile

log = get_logger("pipeline.preflight")


async def prefetch_profile(
    prof_svc: "ProfileService",
    session_id: str,
    db_id: str,
) -> "DatabaseProfile | None":
    """Best-effort warm-load of the cached profile off the event loop.

    Returns ``None`` on cache miss or any error — the caller should treat a
    ``None`` as "no preflight result" and let ``ProfilerStage`` handle the
    cold-cache path normally. Errors are logged at warning level.
    """
    try:
        return await asyncio.to_thread(prof_svc.load, session_id, db_id)
    except Exception as exc:  # noqa: BLE001 — preflight is an optimisation
        log.warning(
            "preflight.profile_prefetch_failed",
            session_id=session_id,
            db_id=db_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None
