"""Table-level description generator — one LLM call per table.

Runs after summaries + quirks are populated. Each table gets a paragraph
describing its purpose, when to query it, and key columns. Display-only
for now (not consumed by any pipeline stage).

Contract::

    await TableDescriptionGenerator(llm).async_generate(
        profile, unified_evidence=""
    ) -> DatabaseProfile  # mutated in place
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..vendored.pipeline_core.models.profile import DatabaseProfile, TableProfile

log = get_logger("profiling.table_description")

_MAX_CHARS = 1000

_PROMPT = """You are describing a database table for a data analyst. Based on the
column metadata below, write a concise paragraph (3-5 sentences) describing:

1. What this table contains — its domain and purpose
2. When to query it — typical analytical use cases
3. Key columns and what they represent

Return ONLY the description text. No JSON, no preamble, no markdown.

Table: {table_name}
Row count: {row_count}

Columns:
{column_details}"""


class _LLMLike(Protocol):
    """Minimal LLM shape — ``async_generate(prompt) -> str``."""

    async def async_generate(self, prompt: str) -> str: ...


def _render_prompt(table: "TableProfile", unified_evidence: str) -> str:
    lines: list[str] = []
    for col in table.columns:
        parts = [f"- {col.name} ({col.type})"]
        if col.short_summary:
            parts.append(f"  Summary: {col.short_summary}")
        if col.long_summary:
            parts.append(f"  Details: {col.long_summary}")
        if col.quirks.semantic_hint:
            parts.append(f"  Semantic hint: {col.quirks.semantic_hint}")
        if col.quirks.aliases:
            parts.append(f"  Aliases: {', '.join(col.quirks.aliases)}")
        if col.quirks.enum_labels:
            labels = ", ".join(
                f"{k}={v}" for k, v in col.quirks.enum_labels.items()
            )
            parts.append(f"  Values: {labels}")
        lines.append("\n".join(parts))

    prompt = _PROMPT.format(
        table_name=table.name,
        row_count=table.row_count,
        column_details="\n\n".join(lines),
    )
    if unified_evidence:
        prompt += f"\n\nAdditional domain context: {unified_evidence}"
    return prompt


class TableDescriptionGenerator:
    """Generate a paragraph per table describing its purpose and key columns."""

    def __init__(self, llm: _LLMLike) -> None:
        self._llm = llm

    async def async_generate(
        self,
        profile: "DatabaseProfile",
        unified_evidence: str = "",
    ) -> "DatabaseProfile":
        """Populate ``description`` on every ``TableProfile`` in *profile*.

        Returns the same instance (mutated in place). Tables with no columns
        or all-empty summaries are skipped (description stays ``""``).
        """
        tables = profile.tables
        if not tables:
            return profile

        total = len(tables)
        log.info("profiling.table_description_started", tables=total)
        populated = 0
        for table in tables:
            if not table.columns:
                continue
            try:
                prompt = _render_prompt(table, unified_evidence)
                raw = await self._llm.async_generate(prompt)
            except Exception as exc:
                log.warning(
                    "profiling.table_description_failed",
                    table=table.name,
                    error=str(exc),
                )
                continue
            desc = raw.strip()
            if desc:
                if len(desc) > _MAX_CHARS:
                    desc = desc[:_MAX_CHARS]
                table.description = desc
                populated += 1
        log.info(
            "profiling.table_description_completed",
            tables=total,
            populated=populated,
        )
        return profile


__all__ = ["TableDescriptionGenerator"]
