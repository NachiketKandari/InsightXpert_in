"""Render DatabaseSchema + DatabaseProfile into a text block for SQL generation prompts."""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.models.profile import ColumnStats, DatabaseProfile
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
from insightxpert_api.vendored.pipeline_core.schema_utils import bridge_tables_section, render_join_hubs

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinGraph
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)


class SchemaFormatter:
    def __init__(self, join_graph: "JoinGraph | None" = None) -> None:
        self._join_graph = join_graph

    def format(
        self,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        metadata_mode: str = "profiling",
        bird_meta: "BirdMetadata | None" = None,
        seed: int | None = None,
    ) -> str:
        """Render schema as a text block for the SQL generation prompt.

        metadata_mode controls which column descriptions are included:
          "none"      — column names and types only, no descriptions
          "bird"      — BIRD CSV descriptions (requires bird_meta)
          "profiling" — LLM-generated short_summary per column (default)
          "fused"     — both bird CSV descriptions and LLM profile summaries

        When a column's bird_enriched_summary is populated (offline synthesis
        pass), it replaces short_summary in profiling/fused modes. This is how
        --bird-enriched-profile takes effect for the non-linked render path.

        When seed is provided, table and column ordering is shuffled for
        candidate diversity. When None (default), tables are alphabetical.
        """
        use_profile = metadata_mode in ("profiling", "fused")
        use_bird = metadata_mode in ("bird", "fused") and bird_meta

        # Build per-column description and stats lookups
        profile_summaries: dict[str, dict[str, str]] = {}
        profile_stats: dict[str, dict[str, ColumnStats]] = {}
        profile_quirks: dict[str, dict[str, object]] = {}
        if use_profile and profile:
            for tp in profile.tables:
                profile_summaries[tp.name] = {
                    cp.name: (cp.bird_enriched_summary or cp.short_summary)
                    for cp in tp.columns
                }
                profile_stats[tp.name] = {cp.name: cp.stats for cp in tp.columns}
                profile_quirks[tp.name] = {cp.name: cp.quirks for cp in tp.columns}

        if seed is not None:
            rng = random.Random(seed)
            tables_ordered = rng.sample(list(schema.tables), len(schema.tables))
        else:
            tables_ordered = sorted(schema.tables, key=lambda t: t.name)

        lines: list[str] = []
        for table in tables_ordered:
            lines.append(f'Table: "{table.name}"')
            lines.append("  Columns:")

            fk_map = {fk.column: (fk.ref_table, fk.ref_column) for fk in table.foreign_keys}
            pk_set = {col.name for col in table.columns if col.primary_key}

            cols_ordered = (
                rng.sample(list(table.columns), len(table.columns))
                if seed is not None else table.columns
            )
            for col in cols_ordered:
                tags: list[str] = []
                if col.name in pk_set:
                    tags.append("PK")
                if col.name in fk_map:
                    ref_t, ref_c = fk_map[col.name]
                    tags.append(f"FK → {ref_t}.{ref_c}")
                tag_str = f", {', '.join(tags)}" if tags else ""

                desc_parts: list[str] = []
                if use_profile:
                    quirks = profile_quirks.get(table.name, {}).get(col.name)
                    s = profile_summaries.get(table.name, {}).get(col.name, "")
                    hint = quirks.semantic_hint if quirks and hasattr(quirks, "semantic_hint") else ""
                    # Fuse short_summary + semantic_hint into one description.
                    if s and hint and hint not in s:
                        desc_parts.append(f"{s} {hint}")
                    elif s:
                        desc_parts.append(s)
                    elif hint:
                        desc_parts.append(hint)
                    # For low-cardinality columns, append actual values so the
                    # model knows what literals to use in WHERE clauses.
                    stats = profile_stats.get(table.name, {}).get(col.name)
                    if stats and stats.sample_values and stats.distinct_count <= 20:
                        # Defence-in-depth: cap individual sample values so a
                        # single mis-profiled column can't blow up the prompt.
                        # Primary prevention is in StatsCollector._should_skip_samples.
                        truncated = [
                            (v[:500] + "…") if isinstance(v, str) and len(v) > 500 else v
                            for v in stats.sample_values
                        ]
                        vals = ", ".join(repr(v) for v in truncated)
                        desc_parts.append(f"Values: [{vals}]")
                    # Quirk enum labels (decode coded values).
                    if quirks and hasattr(quirks, "enum_labels") and quirks.enum_labels:
                        enum_str = ", ".join(
                            f"{k!r}→{v}" for k, v in quirks.enum_labels.items()
                            if v and v != "unknown"
                        )
                        if enum_str:
                            desc_parts.append(f"Labels: {{{enum_str}}}")
                    # Quirk aliases (alternative user-facing names).
                    if quirks and hasattr(quirks, "aliases") and quirks.aliases:
                        col_lower = col.name.lower()
                        col_spaced = col_lower.replace("_", " ")
                        useful = [
                            a for a in quirks.aliases
                            if a.lower() != col_lower and a.lower() != col_spaced
                        ]
                        if useful:
                            desc_parts.append(f"Aliases: {', '.join(useful)}")
                    # Quirk type mismatch warnings.
                    if quirks and hasattr(quirks, "type_mismatch") and quirks.type_mismatch:
                        desc_parts.append(f"Note: {quirks.type_mismatch}")
                if use_bird:
                    b = bird_meta.get(table.name, col.name)
                    if b and b not in desc_parts:
                        desc_parts.append(b)

                desc_str = f": {' | '.join(desc_parts)}" if desc_parts else ""
                lines.append(f'    - "{col.name}" ({col.type}{tag_str}){desc_str}')

            if table.foreign_keys:
                lines.append("  Foreign Keys:")
                for fk in table.foreign_keys:
                    lines.append(f"    - {table.name}.{fk.column} → {fk.ref_table}.{fk.ref_column}")

            lines.append("")

        result = "\n".join(lines).rstrip()

        # Append join hubs from the precomputed JoinGraph (if provided).
        if self._join_graph is not None:
            tables_in_scope = {t.name for t in tables_ordered}
            hubs = render_join_hubs(tables_in_scope, self._join_graph)
            if hubs:
                result += "\n" + hubs

        bridge = bridge_tables_section(schema)
        if bridge:
            result += "\n" + bridge

        logger.debug("Formatted schema: %d chars (mode=%s)", len(result), metadata_mode)
        return result
