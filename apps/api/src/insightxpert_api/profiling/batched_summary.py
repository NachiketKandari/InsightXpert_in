"""Batched column-summary generator — one LLM call per N columns.

The vendored ``SummaryGenerator`` fires 2 LLM calls per column (short + long
summaries). For a 90-column DB that's 180 calls.  This batched variant groups
columns into chunks of ``batch_size`` and emits a single LLM call per chunk
requesting a JSON object keyed by column name.

On partial response (fewer entries than expected, or malformed JSON) we fall
back to per-column single-LLM-call calls for the **missing** columns only.
A structured log event ``profiling.batch_response_partial`` is emitted so
operators can grep for partial batches after the fact.

Contract shape::

    await BatchedSummaryGenerator(llm, batch_size=20).async_generate(
        schema, profile, unified_evidence=""
    ) -> DatabaseProfile  # same mutate-and-return contract as vendored

The LLM's ``async_generate(prompt: str) -> str`` method is used — identical to
the vendored ``BaseLLM`` surface our ``GeminiLLM`` adapter exposes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..logging import get_logger
from ..vendored.pipeline_core.models.profile import (
    ColumnProfile,
    DatabaseProfile,
)
from ..vendored.pipeline_core.models.schema import DatabaseSchema

if TYPE_CHECKING:  # pragma: no cover
    pass

log = get_logger("profiling.batched_summary")


class _LLMLike(Protocol):
    """Minimal LLM shape we depend on — ``async_generate(prompt) -> str``."""

    async def async_generate(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class ColumnRef:
    """Flat reference to a column inside a ``DatabaseProfile``."""

    table_idx: int
    col_idx: int
    table_name: str
    column_name: str
    column_type: str


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

_BATCH_PROMPT_HEADER = """You are summarizing {n} database columns. For each column
below, return a JSON object keyed by that column's exact name, with the shape
{{"short_summary": "...", "long_summary": "..."}}.

Return ONLY valid JSON — no markdown, no preamble, no trailing text.
The JSON object MUST contain exactly one entry per column listed below,
using the exact column names as keys.

short_summary: one sentence describing what this column represents.
long_summary: 2-3 sentences covering meaning, domain, and typical use.
"""

_SINGLE_PROMPT = """You are summarizing a single database column. Return ONLY
valid JSON of the shape {{"short_summary": "...", "long_summary": "..."}}.

short_summary: one sentence describing what this column represents.
long_summary: 2-3 sentences covering meaning, domain, and typical use.

table: {table}
column: {column}
type: {type}
"""


def _render_batch_prompt(refs: list[ColumnRef], unified_evidence: str) -> str:
    lines: list[str] = [_BATCH_PROMPT_HEADER.format(n=len(refs))]
    if unified_evidence:
        lines.append(f"\nShared domain knowledge for this database:\n{unified_evidence}\n")
    lines.append("Columns:")
    for i, ref in enumerate(refs, start=1):
        lines.append(
            f"{i}. column_name: {ref.column_name}\n"
            f"   table: {ref.table_name}\n"
            f"   type: {ref.column_type}"
        )
    return "\n".join(lines)


def _render_single_prompt(ref: ColumnRef) -> str:
    return _SINGLE_PROMPT.format(
        table=ref.table_name,
        column=ref.column_name,
        type=ref.column_type,
    )


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_json_object(raw: str) -> dict[str, object]:
    """Tolerant JSON-object parser for LLM responses.

    Strips code fences, finds the first ``{...}`` match, returns ``{}`` on
    failure. Never raises — callers check ``len(result)`` to detect partial
    responses.
    """
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


# ---------------------------------------------------------------------------
# BatchedSummaryGenerator
# ---------------------------------------------------------------------------


# DECISION(D-061): Batch N columns per LLM call (default 20) instead of 2 calls per column
class BatchedSummaryGenerator:
    """Generate short + long column summaries with 1 LLM call per batch of N columns.

    Unlike the vendored ``SummaryGenerator`` (2 calls per column), this variant
    trades concurrency for cost: one LLM call returns summaries for every
    column in the batch. Partial responses fall back to per-column calls for
    the missing columns only.
    """

    def __init__(self, llm: _LLMLike, batch_size: int = 20) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._llm = llm
        self._batch_size = batch_size

    def _flatten(self, profile: DatabaseProfile) -> list[ColumnRef]:
        refs: list[ColumnRef] = []
        for t_idx, table in enumerate(profile.tables):
            for c_idx, col in enumerate(table.columns):
                refs.append(
                    ColumnRef(
                        table_idx=t_idx,
                        col_idx=c_idx,
                        table_name=table.name,
                        column_name=col.name,
                        column_type=col.type,
                    )
                )
        return refs

    @staticmethod
    def _apply_summary(
        profile: DatabaseProfile,
        ref: ColumnRef,
        short: str,
        long: str,
    ) -> None:
        col: ColumnProfile = profile.tables[ref.table_idx].columns[ref.col_idx]
        profile.tables[ref.table_idx].columns[ref.col_idx] = col.model_copy(
            update={"short_summary": short, "long_summary": long}
        )

    @staticmethod
    def _extract(entry: object) -> tuple[str, str] | None:
        if not isinstance(entry, dict):
            return None
        short = entry.get("short_summary")
        long = entry.get("long_summary")
        if not isinstance(short, str) or not isinstance(long, str):
            return None
        return short, long

    async def _single_fallback(
        self, profile: DatabaseProfile, ref: ColumnRef
    ) -> None:
        prompt = _render_single_prompt(ref)
        try:
            raw = await self._llm.async_generate(prompt)
        except Exception as exc:
            log.warning(
                "profiling.single_fallback_failed",
                table=ref.table_name,
                column=ref.column_name,
                error=str(exc),
            )
            return
        parsed = _parse_json_object(raw)
        pair = self._extract(parsed)
        if pair is None:
            log.warning(
                "profiling.single_fallback_unparseable",
                table=ref.table_name,
                column=ref.column_name,
            )
            return
        self._apply_summary(profile, ref, pair[0], pair[1])

    async def _run_batch(
        self,
        profile: DatabaseProfile,
        refs: list[ColumnRef],
        unified_evidence: str,
        *,
        batch_index: int,
        batch_total: int,
    ) -> None:
        """Run a single batch. Distribute parsed entries; fall back for missing ones."""
        prompt = _render_batch_prompt(refs, unified_evidence)
        raw: str
        try:
            raw = await self._llm.async_generate(prompt)
        except Exception as exc:
            log.warning(
                "profiling.batch_call_failed",
                batch_index=batch_index,
                batch_total=batch_total,
                size=len(refs),
                error=str(exc),
            )
            raw = ""
        parsed = _parse_json_object(raw)

        # Distribute well-formed entries.
        missing: list[ColumnRef] = []
        for ref in refs:
            entry = parsed.get(ref.column_name)
            pair = self._extract(entry)
            if pair is None:
                missing.append(ref)
                continue
            self._apply_summary(profile, ref, pair[0], pair[1])

        if missing:
            log.warning(
                "profiling.batch_response_partial",
                batch_index=batch_index,
                batch_total=batch_total,
                received=len(refs) - len(missing),
                expected=len(refs),
                missing=[m.column_name for m in missing],
            )
            for ref in missing:
                await self._single_fallback(profile, ref)

    async def async_generate(
        self,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        unified_evidence: str = "",
    ) -> DatabaseProfile:
        """Populate ``short_summary`` / ``long_summary`` on every column.

        Returns the same ``DatabaseProfile`` instance (mutated in place) — same
        contract as the vendored ``SummaryGenerator.async_generate``.
        """
        refs = self._flatten(profile)
        if not refs:
            return profile

        batches: list[list[ColumnRef]] = [
            refs[i : i + self._batch_size]
            for i in range(0, len(refs), self._batch_size)
        ]
        batch_total = len(batches)
        log.info(
            "profiling.batched_summary_started",
            columns=len(refs),
            batches=batch_total,
            batch_size=self._batch_size,
        )
        for i, batch in enumerate(batches):
            await self._run_batch(
                profile,
                batch,
                unified_evidence,
                batch_index=i,
                batch_total=batch_total,
            )
        log.info(
            "profiling.batched_summary_completed",
            columns=len(refs),
            batches=batch_total,
        )
        return profile


__all__ = ["BatchedSummaryGenerator", "ColumnRef"]
