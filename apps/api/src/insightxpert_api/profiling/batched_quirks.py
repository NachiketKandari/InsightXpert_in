"""Batched quirk detector — one LLM call per N columns.

Reuses the vendored ``QuirkEnricher`` pure filters (``is_low_cardinality_enum``,
``_values_look_coded``, ``looks_cryptic``, and rule-based ``detect_*``
functions) to decide which columns are worth LLM-enriching. The subset is
batched into groups of ``batch_size``; one prompt per batch asks the LLM for a
JSON object keyed by column name with shape::

    {<column_name>: {"quirks": ["<short phrase>", ...]}, ...}

``quirks`` strings are folded back onto ``ColumnQuirks.aliases`` + any
semantic_hint / enum_labels that the LLM supplies. Matching the vendored
shape exactly would require two separate LLM templates (enum vs cryptic); this
batched path trades that fidelity for cost and uses a unified ``quirks`` list
consumable by downstream linkers.

Partial response → per-column fallback + ``profiling.batch_response_partial``
structlog event, same as ``BatchedSummaryGenerator``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..logging import get_logger
from ..vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnQuirks,
    DatabaseProfile,
)
from ..vendored.pipeline_core.models.schema import DatabaseSchema
from ..vendored.pipeline_core.profiler.quirk_detector import (
    _values_look_coded,
    detect_rule_based_quirks,
    is_low_cardinality_enum,
    looks_cryptic,
)
from .batched_summary import ColumnRef, _parse_json_object

if TYPE_CHECKING:  # pragma: no cover
    pass

log = get_logger("profiling.batched_quirks")


class _LLMLike(Protocol):
    async def async_generate(self, prompt: str) -> str: ...


_BATCH_PROMPT_HEADER = """You are analyzing {n} database columns that have
cryptic names, low-cardinality enum values, or numbered-group patterns.  For
each column below, return a JSON object keyed by the column's exact name,
each entry of shape {{"quirks": ["<short phrase>", ...]}}.

Each "quirks" list should contain 1-4 short (<=8 words) phrases that would
help a downstream SQL generator understand the column — e.g. expansions of
cryptic abbreviations, enum-value meanings, alternative user-facing names.

Return ONLY valid JSON — no markdown, no preamble, no trailing text. The JSON
object MUST contain exactly one entry per column listed below, using the
exact column names as keys.
"""

_SINGLE_PROMPT = """You are analyzing one database column. Return ONLY valid
JSON of shape {{"quirks": ["<short phrase>", ...]}} with 1-4 short phrases.

table: {table}
column: {column}
type: {type}
sample values: {samples}
"""


def _select_llm_worthy(profile: DatabaseProfile) -> list[ColumnRef]:
    """Return column references that the vendored quirk filters would have
    LLM-called. Re-uses the vendored pure predicates — no copy-paste."""

    refs: list[ColumnRef] = []
    for t_idx, table in enumerate(profile.tables):
        for c_idx, col in enumerate(table.columns):
            enum_like = (
                is_low_cardinality_enum(col)
                and _values_look_coded(col.stats.sample_values)
            )
            # ColumnQuirks.numbered_group may be unset here — tests call us
            # without the rule-based detector having run. That's fine; we
            # rely only on is_low_cardinality_enum + looks_cryptic when the
            # quirk attribute is absent.
            numbered = (
                (col.quirks and col.quirks.numbered_group is not None)
                if col.quirks is not None
                else False
            )
            if enum_like or looks_cryptic(col.name) or numbered:
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


def _render_batch_prompt(
    refs: list[ColumnRef], profile: DatabaseProfile
) -> str:
    lines: list[str] = [_BATCH_PROMPT_HEADER.format(n=len(refs))]
    lines.append("Columns:")
    for i, ref in enumerate(refs, start=1):
        col = profile.tables[ref.table_idx].columns[ref.col_idx]
        samples = ", ".join(str(s) for s in col.stats.sample_values[:10])
        lines.append(
            f"{i}. column_name: {ref.column_name}\n"
            f"   table: {ref.table_name}\n"
            f"   type: {ref.column_type}\n"
            f"   sample_values: {samples}"
        )
    return "\n".join(lines)


def _render_single_prompt(ref: ColumnRef, profile: DatabaseProfile) -> str:
    col = profile.tables[ref.table_idx].columns[ref.col_idx]
    samples = ", ".join(str(s) for s in col.stats.sample_values[:10])
    return _SINGLE_PROMPT.format(
        table=ref.table_name,
        column=ref.column_name,
        type=ref.column_type,
        samples=samples,
    )


def _apply_quirks(
    profile: DatabaseProfile, ref: ColumnRef, quirks: list[str]
) -> None:
    col: ColumnProfile = profile.tables[ref.table_idx].columns[ref.col_idx]
    q = col.quirks or ColumnQuirks()
    # Fold into aliases — the vendored shape we have room for without
    # guessing whether each phrase is semantic_hint vs enum_label.
    existing = set(q.aliases)
    merged = list(q.aliases)
    for phrase in quirks:
        s = str(phrase).strip()
        if s and s not in existing:
            merged.append(s)
            existing.add(s)
    q.aliases = merged
    col.quirks = q


def _extract_quirks(entry: object) -> list[str] | None:
    if not isinstance(entry, dict):
        return None
    quirks = entry.get("quirks")
    if not isinstance(quirks, list):
        return None
    return [str(x) for x in quirks if isinstance(x, (str, int, float))]


class BatchedQuirkDetector:
    """Batched LLM quirk detector — 1 call per N LLM-worthy columns."""

    def __init__(self, llm: _LLMLike, batch_size: int = 20) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._llm = llm
        self._batch_size = batch_size

    async def _single_fallback(
        self, profile: DatabaseProfile, ref: ColumnRef
    ) -> None:
        prompt = _render_single_prompt(ref, profile)
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
        quirks = _extract_quirks(parsed)
        if quirks is None:
            log.warning(
                "profiling.single_fallback_unparseable",
                table=ref.table_name,
                column=ref.column_name,
            )
            return
        _apply_quirks(profile, ref, quirks)

    async def _run_batch(
        self,
        profile: DatabaseProfile,
        refs: list[ColumnRef],
        *,
        batch_index: int,
        batch_total: int,
    ) -> None:
        prompt = _render_batch_prompt(refs, profile)
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

        missing: list[ColumnRef] = []
        for ref in refs:
            entry = parsed.get(ref.column_name)
            quirks = _extract_quirks(entry)
            if quirks is None:
                missing.append(ref)
                continue
            _apply_quirks(profile, ref, quirks)

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

    async def async_enrich(
        self,
        profile: DatabaseProfile,
        schema: DatabaseSchema,
    ) -> DatabaseProfile:
        """Run rule-based quirks in-place, then batched LLM enrichment.

        Returns the mutated ``DatabaseProfile`` (matching vendored shape).
        Columns that fail the vendored filters are left untouched.
        """
        # Phase 1: rule-based — cheap + deterministic. Populates
        # ColumnQuirks.numbered_group / fk_alias / etc.
        detect_rule_based_quirks(profile, schema)

        refs = _select_llm_worthy(profile)
        if not refs:
            log.info("profiling.batched_quirks_no_candidates")
            return profile

        batches: list[list[ColumnRef]] = [
            refs[i : i + self._batch_size]
            for i in range(0, len(refs), self._batch_size)
        ]
        batch_total = len(batches)
        log.info(
            "profiling.batched_quirks_started",
            candidates=len(refs),
            batches=batch_total,
            batch_size=self._batch_size,
        )
        for i, batch in enumerate(batches):
            await self._run_batch(
                profile, batch, batch_index=i, batch_total=batch_total
            )
        log.info(
            "profiling.batched_quirks_completed",
            candidates=len(refs),
            batches=batch_total,
        )
        return profile


__all__ = ["BatchedQuirkDetector"]
