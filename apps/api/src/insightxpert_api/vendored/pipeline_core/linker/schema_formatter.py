"""Five schema text representation variants for trial SQL generation."""
from __future__ import annotations

import logging
import re
import string
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.models.profile import ColumnProfile, DatabaseProfile, TableProfile
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema, TableSchema
from insightxpert_api.vendored.pipeline_core.profiler.lsh_builder import LSHIndex

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
    from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorIndex

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[^\w\s]")


class SchemaVariantFormatter:
    """Produces the 5 schema text variants prescribed by the paper (Section 3)."""

    # ------------------------------------------------------------------
    # Public variant methods
    # ------------------------------------------------------------------

    def full_schema(self, schema: DatabaseSchema) -> str:
        """Variant 1: table/column names, types, PK/FK. No summaries."""
        result = self._render_tables(schema, tables_columns=None, summary_mode="none", profile=None)
        logger.debug("full_schema: %d chars", len(result))
        return result

    def minimal_profile(self, schema: DatabaseSchema, profile: DatabaseProfile) -> str:
        """Variant 2: full schema + short_summary per column."""
        result = self._render_tables(schema, tables_columns=None, summary_mode="short", profile=profile)
        logger.debug("minimal_profile: %d chars", len(result))
        return result

    def maximal_profile(self, schema: DatabaseSchema, profile: DatabaseProfile) -> str:
        """Variant 3: full schema + long_summary per column."""
        result = self._render_tables(schema, tables_columns=None, summary_mode="long", profile=profile)
        logger.debug("maximal_profile: %d chars", len(result))
        return result

    def focused_schema(
        self,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        lsh_index: LSHIndex,
        question: str,
        evidence: str = "",
        vector_index: VectorIndex | None = None,
        llm: BaseLLM | None = None,
    ) -> str:
        """Variant 4: columns matched by LSH value similarity and/or semantic similarity.

        Tokenizes the question AND evidence (words + 2-grams + 3-grams), queries LSH for each,
        collects matched table.column IDs. If a vector index and LLM are provided, also
        embeds the question and retrieves semantically similar columns. Always includes
        PK and FK columns of any matched table. Falls back to full_schema if nothing matches.
        """
        tokens = self._tokenize(question)
        if evidence:
            tokens += self._tokenize(evidence)
        matched_col_ids: set[str] = set()
        for tok in tokens:
            if len(tok) >= 2:
                for col_id in lsh_index.query(tok):
                    matched_col_ids.add(col_id)

        # Semantic matching via vector index
        if vector_index is not None and llm is not None:
            query_text = question if not evidence else f"{question} {evidence}"
            try:
                query_embedding = llm.embed([query_text])[0]
                semantic_hits = vector_index.search(query_embedding, top_k=10)
                sem_count = 0
                for col_id, score in semantic_hits:
                    if score > 0.3:
                        matched_col_ids.add(col_id)
                        sem_count += 1
                logger.debug(
                    "focused_schema: %d semantic matches (threshold=0.3)", sem_count
                )
            except Exception as exc:
                logger.warning(
                    "Semantic matching failed, continuing with LSH only: %s", exc
                )

        if not matched_col_ids:
            logger.debug("focused_schema: no LSH matches, falling back to full_schema")
            result = self.full_schema(schema)
            logger.debug("focused_schema (fallback): %d chars", len(result))
            return result

        # Build {table_name: set of matched column names}
        table_cols: dict[str, set[str]] = {}
        for col_id in matched_col_ids:
            parts = col_id.split(".", 1)
            if len(parts) == 2:
                table_cols.setdefault(parts[0], set()).add(parts[1])

        # Expand: always include PK and FK columns for each matched table
        for table in schema.tables:
            if table.name not in table_cols:
                continue
            pk_cols = {col.name for col in table.columns if col.primary_key}
            fk_cols = {fk.column for fk in table.foreign_keys}
            table_cols[table.name] |= pk_cols | fk_cols

        tables_columns = [
            (tname, sorted(cols)) for tname, cols in sorted(table_cols.items())
        ]
        result = self._render_tables(
            schema, tables_columns=tables_columns, summary_mode="short", profile=profile
        )
        logger.debug("focused_schema: %d chars (%d tables)", len(result), len(tables_columns))
        return result

    def full_profile(self, schema: DatabaseSchema, profile: DatabaseProfile) -> str:
        """Variant 5: everything — types, PK/FK, short_summary, long_summary, key stats."""
        result = self._render_tables(schema, tables_columns=None, summary_mode="full", profile=profile)
        logger.debug("full_profile: %d chars", len(result))
        return result

    # ------------------------------------------------------------------
    # Internal rendering
    # ------------------------------------------------------------------

    def _render_tables(
        self,
        schema: DatabaseSchema,
        tables_columns: list[tuple[str, list[str]]] | None,
        summary_mode: str,
        profile: DatabaseProfile | None,
    ) -> str:
        """Shared rendering logic.

        tables_columns: if None, include all tables/columns; otherwise a list of
            (table_name, [column_names]) specifying the subset to render.
        summary_mode: "none" | "short" | "long" | "full"
        """
        # Build profile lookups
        short_map: dict[str, dict[str, str]] = {}
        long_map: dict[str, dict[str, str]] = {}
        stats_map: dict[str, dict[str, str]] = {}
        col_stats_map: dict[str, dict[str, ColumnProfile]] = {}
        if profile:
            for tp in profile.tables:
                short_map[tp.name] = {cp.name: cp.short_summary for cp in tp.columns}
                long_map[tp.name] = {cp.name: cp.long_summary for cp in tp.columns}
                stats_map[tp.name] = {
                    cp.name: self._format_stats(cp)
                    for cp in tp.columns
                }
                col_stats_map[tp.name] = {cp.name: cp for cp in tp.columns}

        # Determine which tables/columns to render
        if tables_columns is None:
            subset: dict[str, list[str] | None] = {t.name: None for t in sorted(schema.tables, key=lambda t: t.name)}
        else:
            subset = {tname: cols for tname, cols in tables_columns}

        lines: list[str] = []
        for table in sorted(schema.tables, key=lambda t: t.name):
            if table.name not in subset:
                continue
            col_filter = subset[table.name]  # None = all columns

            fk_map = {fk.column: (fk.ref_table, fk.ref_column) for fk in table.foreign_keys}
            pk_set = {col.name for col in table.columns if col.primary_key}

            col_lines: list[str] = []
            included_fks: list = []
            for col in table.columns:
                if col_filter is not None and col.name not in col_filter:
                    continue

                tags: list[str] = []
                if col.name in pk_set:
                    tags.append("PK")
                if col.name in fk_map:
                    ref_t, ref_c = fk_map[col.name]
                    tags.append(f"FK → {ref_t}.{ref_c}")
                    included_fks.append((col.name, ref_t, ref_c))
                tag_str = f", {', '.join(tags)}" if tags else ""

                col_line = f'    - "{col.name}" ({col.type}{tag_str})'

                if summary_mode in ("short", "full"):
                    s = short_map.get(table.name, {}).get(col.name, "")
                    if s:
                        col_line += f": {s}"
                if summary_mode in ("long", "full"):
                    s = long_map.get(table.name, {}).get(col.name, "")
                    if s:
                        col_line += f" | {s}" if summary_mode == "full" else f": {s}"
                if summary_mode == "full":
                    s = stats_map.get(table.name, {}).get(col.name, "")
                    if s:
                        col_line += f" [{s}]"

                # Inject actual values for low-cardinality columns
                if summary_mode != "none":
                    cp = col_stats_map.get(table.name, {}).get(col.name)
                    if cp and cp.stats and cp.stats.sample_values and cp.stats.distinct_count <= 20:
                        vals = ", ".join(repr(v) for v in cp.stats.sample_values)
                        col_line += f" | Values: [{vals}]"

                col_lines.append(col_line)

            if not col_lines:
                continue

            lines.append(f'Table: "{table.name}"')
            lines.append("  Columns:")
            lines.extend(col_lines)

            if included_fks:
                lines.append("  Foreign Keys:")
                for col_name, ref_t, ref_c in included_fks:
                    lines.append(f"    - {table.name}.{col_name} → {ref_t}.{ref_c}")

            lines.append("")

        return "\n".join(lines).rstrip()

    @staticmethod
    def _format_stats(cp: ColumnProfile) -> str:
        """Compact stats string for full_profile variant."""
        parts = []
        if cp.stats:
            s = cp.stats
            if s.distinct_count is not None:
                parts.append(f"distinct={s.distinct_count}")
            if s.sample_values:
                samples = ", ".join(str(v) for v in s.sample_values[:5])
                parts.append(f"samples=[{samples}]")
        return "; ".join(parts)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Return words + 2-grams + 3-grams from text (lowercased, punct stripped)."""
        cleaned = _PUNCT_RE.sub(" ", text.lower())
        words = [w for w in cleaned.split() if w]
        tokens = list(words)
        for n in (2, 3):
            for i in range(len(words) - n + 1):
                tokens.append(" ".join(words[i:i + n]))
        return tokens
