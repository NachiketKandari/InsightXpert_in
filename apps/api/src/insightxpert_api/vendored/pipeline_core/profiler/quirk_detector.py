"""Detect schema-linking quirks in profiled databases.

Two-phase detection:
1. Rule-based: cheap, deterministic. Runs on stats + names. No LLM needed.
2. LLM-enriched: async, semaphore-limited. Called only for columns where rule-based
   found something worth labeling (cryptic abbreviations, foreign-language enums,
   numbered families).

Populates ColumnProfile.quirks (ColumnQuirks) in-place.

Usage:
    QuirkEnricher(llm).async_enrich(profile, schema, bird_meta=...)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnQuirks,
    DatabaseProfile,
)

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
    from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)

# --- Rule-based detectors -------------------------------------------------

_SPECIAL_CHAR_RE = re.compile(r"[ \(\)\-/\.]")
_NUMBERED_SUFFIX_RE = re.compile(r"^(.*?)(\d+)$")
_FK_PREFIXES = ("link_to_", "ref_", "fk_")
_SYMBOL_VALUES = {"+", "-", "=", "#", "++", "--", "+-", "-+", "Y", "N", "y", "n"}

_COMMON_SHORT_NAMES = {
    "id", "name", "date", "type", "code", "key", "url", "tag", "bank",
    "age", "sex", "row", "num", "qty", "amt", "ref", "lat", "lng", "lon",
    "zip", "day", "year", "city", "time", "rank",
}


def detect_special_chars(col: ColumnProfile) -> bool:
    """Column name has spaces or parens/brackets/slashes."""
    return bool(_SPECIAL_CHAR_RE.search(col.name))


def detect_symbolic_values(col: ColumnProfile) -> bool:
    """Column stores short symbolic values like '+', '-', '=', '#'."""
    if col.type.upper() != "TEXT":
        return False
    samples = [s for s in col.stats.sample_values if s is not None]
    if not samples:
        return False
    short_symbolic = sum(
        1 for s in samples if len(str(s).strip()) <= 3 and str(s).strip() in _SYMBOL_VALUES
    )
    all_sym = sum(
        1 for s in samples
        if str(s).strip() and all(c in "+-=#|" for c in str(s).strip())
    )
    return (short_symbolic + all_sym) >= max(1, len(samples) // 2)


def detect_fk_alias(col_name: str, schema_pk_names: set[str]) -> str | None:
    """If col matches FK prefix pattern and the stripped name is a known PK, return that PK."""
    cn = col_name.lower()
    for prefix in _FK_PREFIXES:
        if cn.startswith(prefix):
            stub = cn[len(prefix):]
            candidate = f"{stub}_id"
            if candidate in schema_pk_names:
                return candidate
            for pk in schema_pk_names:
                if pk.endswith(f"{stub}_id") or pk == stub:
                    return pk
    return None


def detect_type_mismatch(col: ColumnProfile) -> str | None:
    """Declared type doesn't match actual values."""
    t = col.type.upper()
    samples = [s for s in col.stats.sample_values if s]
    if not samples:
        return None

    if t in ("DATE", "DATETIME", "TIMESTAMP"):
        yyyymm_ish = sum(1 for s in samples if re.fullmatch(r"\d{6}", str(s)))
        yyyymmdd_ish = sum(1 for s in samples if re.fullmatch(r"\d{8}", str(s)))
        iso_ish = sum(1 for s in samples if re.match(r"\d{4}-\d{2}", str(s)))
        if yyyymm_ish >= len(samples) * 0.5 and iso_ish == 0:
            return "declared DATE, stores YYYYMM-format text"
        if yyyymmdd_ish >= len(samples) * 0.5 and iso_ish == 0:
            return "declared DATE, stores YYYYMMDD-format text"

    if "(y/n)" in col.name.lower() or "(yes/no)" in col.name.lower():
        int_ish = sum(1 for s in samples if str(s).strip() in ("0", "1"))
        if int_ish >= len(samples) * 0.5:
            return "name says Y/N but stores 0/1"

    return None


def detect_numbered_group(col_name: str, all_col_names: list[str]) -> str | None:
    """If column is part of a numbered family (A1-A16, q1/q2/q3), return the prefix."""
    match = _NUMBERED_SUFFIX_RE.match(col_name)
    if not match:
        return None
    prefix, num = match.groups()
    if not prefix:
        return None
    siblings = 0
    for other in all_col_names:
        if other == col_name:
            continue
        m = _NUMBERED_SUFFIX_RE.match(other)
        if m and m.group(1) == prefix:
            siblings += 1
    if siblings >= 2:
        return prefix
    return None


def is_low_cardinality_enum(col: ColumnProfile) -> bool:
    """Text column with <=10 distinct short values is likely a coded enum."""
    if col.type.upper() != "TEXT":
        return False
    if col.stats.distinct_count == 0 or col.stats.distinct_count > 10:
        return False
    samples = col.stats.sample_values
    if not samples:
        return False
    avg_len = sum(len(str(s)) for s in samples) / len(samples)
    return avg_len <= 30


def looks_cryptic(col_name: str) -> bool:
    """Heuristic: column name is likely a cryptic abbreviation worth explaining.

    Criteria: <=4 chars AND not a common English short word, or no vowels (KCT, RVVT).
    Skips obvious names like "date", "name", "type", etc.
    """
    n = col_name.lower().strip()
    for suffix in ("_id", "_code", "_name", "_date", "_key"):
        if n.endswith(suffix):
            return False
    if n in _COMMON_SHORT_NAMES:
        return False
    if len(n) <= 4 and n not in _COMMON_SHORT_NAMES:
        return True
    letters = re.sub(r"[^a-z]", "", n)
    if letters and not re.search(r"[aeiou]", letters) and len(letters) <= 6:
        return True
    return False


def _values_look_coded(values: list[str]) -> bool:
    """True if values look like codes (short, non-English, symbolic, etc.)."""
    if not values:
        return False
    for v in values:
        s = str(v).strip()
        if not s:
            continue
        if all(c in "+-=#|0123456789" for c in s) and len(s) <= 3:
            return True
        if s.isupper() and len(s) <= 15 and re.fullmatch(r"[A-Z ]+", s):
            return True
        if any(ord(c) > 127 for c in s):
            return True
    return False


def _parse_json_dict(raw: str) -> dict:
    """Extract JSON object from LLM response, handling fenced blocks."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def detect_rule_based_quirks(
    profile: DatabaseProfile, schema: "DatabaseSchema"
) -> None:
    """Populate rule-based fields on ColumnQuirks for every column, in-place."""
    pk_names: set[str] = set()
    for tbl in schema.tables:
        for col in tbl.columns:
            if col.primary_key:
                pk_names.add(col.name.lower())

    for table in profile.tables:
        all_names = [c.name for c in table.columns]
        for col in table.columns:
            q = col.quirks or ColumnQuirks()
            q.has_special_chars = detect_special_chars(col)
            q.symbolic_values = detect_symbolic_values(col)
            q.numbered_group = detect_numbered_group(col.name, all_names)
            q.type_mismatch = detect_type_mismatch(col)
            q.fk_alias = detect_fk_alias(col.name, pk_names)
            col.quirks = q


# --- LLM prompts ---------------------------------------------------------

_ENUM_ENRICH_PROMPT = """You are analyzing a database column to help an LLM understand its values.

Table: {table}
Column: {column}
Type: {type}
Distinct count: {distinct_count}
All values: {values}
{bird_hint}

Some of these values may be codes, abbreviations, or foreign-language terms.
For each value, provide a short English label (2-5 words) describing what it means.

If documentation is provided above, it is GROUND TRUTH — use it verbatim and do NOT override with common-sense banking/domain conventions. Single-letter codes frequently mean the OPPOSITE of what common convention would suggest (e.g. in some schemas 'A' means "finished" and 'C' means "running", not "active" and "closed").
If the meaning is obvious from the value itself (e.g. "active" or "January"), repeat it.
If you genuinely don't know and there's no documentation, write "unknown".

Return ONLY a JSON object mapping each value to its label, no explanation:
{{"value1": "label1", "value2": "label2", ...}}"""


_CRYPTIC_ENRICH_PROMPT = """You are analyzing a database column with a cryptic name to help an LLM understand it.

Table: {table}
Column: {column}
Type: {type}
Sample values: {samples}
Stats: min={min_v}, max={max_v}, distinct={distinct}
{context}
{bird_hint}

The column name is cryptic or abbreviated. Based on the data and any documentation provided, give:
1. A short semantic hint (one sentence) describing what this column represents
2. 2-4 alternative names a user might use when asking about this column in natural language

If documentation is provided above, use it as ground truth. Otherwise infer from values.

Return ONLY a JSON object, no explanation:
{{"semantic_hint": "...", "aliases": ["...", "..."]}}"""


# --- Async enricher -------------------------------------------------------


class QuirkEnricher:
    """Phase-2 LLM enricher. Concurrent, semaphore-limited.

    Consumes rule-based-detected quirks and fills in enum_labels/semantic_hint/aliases
    for columns flagged as cryptic or enum-like.
    """

    def __init__(self, llm: "BaseLLM", concurrency: int = 10):
        self._llm = llm
        self._sem = asyncio.Semaphore(concurrency)

    async def async_enrich(
        self,
        profile: DatabaseProfile,
        schema: "DatabaseSchema",
        bird_meta: "BirdMetadata | None" = None,
        max_calls: int = 200,
    ) -> tuple[DatabaseProfile, int]:
        """Run rule-based detection then LLM enrichment. Returns (profile, llm_call_count)."""
        # Phase 1: rules (in-place)
        detect_rule_based_quirks(profile, schema)

        # Phase 2: LLM enrichment (concurrent)
        tasks: list[tuple[str, str, asyncio.Task]] = []

        for table in profile.tables:
            table_context = (
                f"Other columns in this table: "
                f"{', '.join(c.name for c in table.columns if c.name != '')[:500]}"
            )

            for col in table.columns:
                if len(tasks) >= max_calls:
                    break

                # Enrich enum labels for low-cardinality coded text columns.
                # Pass BIRD docs so the LLM doesn't guess from common banking/domain
                # conventions — single-letter codes often mean the opposite of what
                # convention would suggest (e.g. financial.loan.status: 'A'=finished,
                # 'C'=running, not 'A'=active, 'C'=closed).
                if (
                    is_low_cardinality_enum(col)
                    and not col.quirks.enum_labels
                    and _values_look_coded(col.stats.sample_values)
                ):
                    enum_bird_desc = bird_meta.get(table.name, col.name) if bird_meta else ""
                    task = asyncio.create_task(
                        self._enrich_enum(table.name, col, enum_bird_desc)
                    )
                    tasks.append((table.name, col.name, task))

                # Enrich semantic hint for cryptic or numbered columns
                needs_semantic = (
                    looks_cryptic(col.name) or col.quirks.numbered_group is not None
                )
                if needs_semantic and not col.quirks.semantic_hint:
                    if len(tasks) >= max_calls:
                        break
                    bird_desc = bird_meta.get(table.name, col.name) if bird_meta else ""
                    task = asyncio.create_task(
                        self._enrich_cryptic(
                            table.name, col, table_context, bird_desc
                        )
                    )
                    tasks.append((table.name, col.name, task))

            if len(tasks) >= max_calls:
                logger.warning(
                    "QuirkEnricher hit max_calls=%d, stopping early", max_calls
                )
                break

        # Wait for all tasks
        for table_name, col_name, task in tasks:
            try:
                await task
            except Exception as exc:
                logger.warning(
                    "Quirk enrichment failed for %s.%s: %s",
                    table_name, col_name, exc,
                )

        return profile, len(tasks)

    async def _enrich_enum(
        self, table_name: str, col: ColumnProfile, bird_desc: str = ""
    ) -> None:
        bird_hint = f"Official documentation:\n{bird_desc}" if bird_desc else ""
        prompt = _ENUM_ENRICH_PROMPT.format(
            table=table_name,
            column=col.name,
            type=col.type,
            distinct_count=col.stats.distinct_count,
            values=", ".join(str(v) for v in col.stats.sample_values),
            bird_hint=bird_hint,
        )
        async with self._sem:
            raw = await self._llm.async_generate(prompt)
        labels = _parse_json_dict(raw)
        if labels:
            col.quirks.enum_labels = {str(k): str(v) for k, v in labels.items()}
            logger.info(
                "Enum labels for %s.%s: %d values",
                table_name, col.name, len(col.quirks.enum_labels),
            )

    async def _enrich_cryptic(
        self,
        table_name: str,
        col: ColumnProfile,
        context: str,
        bird_desc: str,
    ) -> None:
        bird_hint = f"Official documentation: {bird_desc}" if bird_desc else ""
        prompt = _CRYPTIC_ENRICH_PROMPT.format(
            table=table_name,
            column=col.name,
            type=col.type,
            samples=", ".join(str(v) for v in col.stats.sample_values[:15]),
            min_v=col.stats.min_value or "?",
            max_v=col.stats.max_value or "?",
            distinct=col.stats.distinct_count,
            context=context,
            bird_hint=bird_hint,
        )
        async with self._sem:
            raw = await self._llm.async_generate(prompt)
        parsed = _parse_json_dict(raw)
        if parsed:
            col.quirks.semantic_hint = str(parsed.get("semantic_hint", ""))
            aliases = parsed.get("aliases", [])
            if isinstance(aliases, list):
                col.quirks.aliases = [str(a) for a in aliases]
            logger.info(
                "Cryptic hint for %s.%s: %s",
                table_name, col.name, col.quirks.semantic_hint[:60],
            )


# --- Backwards-compatible sync wrapper ------------------------------------


def enrich_with_llm(
    profile: DatabaseProfile,
    llm: "BaseLLM",
    max_calls: int = 50,
    bird_meta: "BirdMetadata | None" = None,
    schema: "DatabaseSchema | None" = None,
) -> int:
    """Sync wrapper around QuirkEnricher for scripts that aren't already async.

    Uses the sync .generate() path — slower than the async version but simpler.
    Assumes detect_rule_based_quirks() has already populated Phase-1 quirks,
    unless `schema` is provided (in which case it runs Phase 1 too).
    """
    if schema is not None:
        detect_rule_based_quirks(profile, schema)

    calls = 0

    for table in profile.tables:
        table_context = (
            f"Other columns in this table: "
            f"{', '.join(c.name for c in table.columns if c.name != '')[:500]}"
        )

        for col in table.columns:
            if calls >= max_calls:
                logger.warning("Quirk enrichment hit max_calls=%d", max_calls)
                return calls

            if (
                is_low_cardinality_enum(col)
                and not col.quirks.enum_labels
                and _values_look_coded(col.stats.sample_values)
            ):
                enum_bird_desc = bird_meta.get(table.name, col.name) if bird_meta else ""
                enum_bird_hint = f"Official documentation:\n{enum_bird_desc}" if enum_bird_desc else ""
                prompt = _ENUM_ENRICH_PROMPT.format(
                    table=table.name, column=col.name, type=col.type,
                    distinct_count=col.stats.distinct_count,
                    values=", ".join(str(v) for v in col.stats.sample_values),
                    bird_hint=enum_bird_hint,
                )
                try:
                    raw = llm.generate(prompt)
                    calls += 1
                    labels = _parse_json_dict(raw)
                    if labels:
                        col.quirks.enum_labels = {str(k): str(v) for k, v in labels.items()}
                except Exception as exc:
                    logger.warning("Enum enrichment failed for %s.%s: %s",
                                   table.name, col.name, exc)

            needs_semantic = (
                looks_cryptic(col.name) or col.quirks.numbered_group is not None
            )
            if needs_semantic and not col.quirks.semantic_hint:
                if calls >= max_calls:
                    return calls
                bird_desc = bird_meta.get(table.name, col.name) if bird_meta else ""
                bird_hint = f"Official documentation: {bird_desc}" if bird_desc else ""
                prompt = _CRYPTIC_ENRICH_PROMPT.format(
                    table=table.name, column=col.name, type=col.type,
                    samples=", ".join(str(v) for v in col.stats.sample_values[:15]),
                    min_v=col.stats.min_value or "?",
                    max_v=col.stats.max_value or "?",
                    distinct=col.stats.distinct_count,
                    context=table_context,
                    bird_hint=bird_hint,
                )
                try:
                    raw = llm.generate(prompt)
                    calls += 1
                    parsed = _parse_json_dict(raw)
                    if parsed:
                        col.quirks.semantic_hint = str(parsed.get("semantic_hint", ""))
                        aliases = parsed.get("aliases", [])
                        if isinstance(aliases, list):
                            col.quirks.aliases = [str(a) for a in aliases]
                except Exception as exc:
                    logger.warning("Cryptic enrichment failed for %s.%s: %s",
                                   table.name, col.name, exc)

    return calls
