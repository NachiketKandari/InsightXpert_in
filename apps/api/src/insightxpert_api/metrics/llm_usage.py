"""Unified LLM usage emission — Phase 1.2.

One helper every LLM call site drops into a ``try/finally`` block so we can
never *silently* skip a spend record. Writes to the extended ``query_metrics``
table with the new ``source`` / ``provider`` / ``model`` / ``cost_usd`` /
``pricing_version`` / ``source_ref_id`` columns (see alembic 20260425_0001).

Design contract:
  * MUST NOT raise. DB failures log a structured ``llm_usage.record_failed``
    event but never bubble to the caller — we'd rather lose a metric than fail
    a user request. Callers still wrap the block in ``try/finally`` so usage is
    emitted even when the LLM-using code path raised mid-flight.
  * Returns the new row id (hex uuid) for correlation, or the uuid it *would*
    have written if the DB write failed, so log lines can still be joined
    against structured events.

The four supported sources:
  * ``chat`` — chat turn (existing chat route, ``_record_turn`` back-compat)
  * ``profile`` — profiling run (summaries + quirks batches)
  * ``automation`` — AI-SQL generation during an automation run
  * ``trigger_compile`` — NL trigger compilation
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from ..db.engine import get_engine
from ..logging import get_logger
from .pricing import cost_usd as _cost_usd
from .table import query_metrics

log = get_logger("metrics.llm_usage")

LlmUsageSource = Literal["chat", "profile", "automation", "trigger_compile"]


def record_llm_usage(
    *,
    source: LlmUsageSource,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    user_id: str,
    session_id: str | None = None,
    source_ref_id: str | None = None,
    # Optional back-compat fields (kept so a single helper covers both
    # chat-turn-shaped rows and profile/automation/trigger-compile rows).
    question: str | None = None,
    final_sql: str | None = None,
    agent_mode: str | None = None,
    duration_ms: int | None = None,
    db_id: str | None = None,
    conversation_id: str | None = None,
    cost_usd_override: float | None = None,
) -> str:
    """Insert one ``query_metrics`` row. Never raises.

    ``cost_usd_override`` is only respected when non-None; otherwise we compute
    it from ``(model, input_tokens, output_tokens)`` via the pricing registry.
    """
    row_id = uuid.uuid4().hex
    try:
        tokens_in = int(input_tokens or 0)
        tokens_out = int(output_tokens or 0)
        if cost_usd_override is not None:
            computed_cost = float(cost_usd_override)
            from .pricing import PRICING_VERSION

            pricing_version = PRICING_VERSION
        else:
            computed_cost, pricing_version = _cost_usd(
                model, tokens_in, tokens_out
            )

        # query_metrics.conversation_id is NOT NULL — fill with source_ref_id
        # or row_id so non-chat emissions (profile/automation/trigger_compile)
        # don't blow the constraint.
        convo_for_row = (
            conversation_id or source_ref_id or row_id
        )
        # question is NOT NULL too; default to a deterministic source label
        # so admin views can still render the row.
        question_for_row = (
            question if question is not None else f"[{source}]"
        )

        values: dict[str, Any] = {
            "id": row_id,
            "user_id": user_id,
            "conversation_id": convo_for_row,
            "db_id": db_id,
            "question": question_for_row,
            "final_sql": final_sql,
            "agent_mode": agent_mode,
            "tokens_in": tokens_in or None,
            "tokens_out": tokens_out or None,
            "duration_ms": duration_ms,
            "thumbs": None,
            "stage_timings_json": None,
            "agent_trace_summary_json": None,
            "created_at": int(time.time()),
            "source": source,
            "provider": provider,
            "model": model,
            "cost_usd": computed_cost,
            "pricing_version": pricing_version,
            "source_ref_id": source_ref_id,
        }
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(query_metrics.insert().values(**values))
    except Exception as exc:  # noqa: BLE001 — best-effort, never user-facing
        # Structured event carries the full payload so a cron log-scanner can
        # reconstruct rows after the fact (see spend-quota design §3.3).
        log.error(
            "llm_usage.record_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            source=source,
            provider=provider,
            model=model,
            user_id=user_id,
            source_ref_id=source_ref_id,
            tokens_in=int(input_tokens or 0),
            tokens_out=int(output_tokens or 0),
        )
    return row_id


__all__ = ["LlmUsageSource", "record_llm_usage"]
