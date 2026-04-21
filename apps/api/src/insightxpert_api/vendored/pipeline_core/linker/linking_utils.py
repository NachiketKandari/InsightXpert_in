"""Shared helpers for schema linking: field union, join paths, pruned schema rendering."""
from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.linker.trial_query import ExtractedFields
from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinEdge, JoinGraph
from insightxpert_api.vendored.pipeline_core.models.profile import ColumnStats, DatabaseProfile
from insightxpert_api.vendored.pipeline_core.models.query import LinkedField, SchemaLinkResult
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
from insightxpert_api.vendored.pipeline_core.schema_utils import bridge_tables_section, render_join_hubs

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FK graph helpers for BFS bridge discovery + MST join path pruning
# ---------------------------------------------------------------------------


def _build_fk_graph(
    schema: DatabaseSchema,
) -> tuple[dict[str, list[tuple[str, JoinEdge]]], dict[str, str]]:
    """Build a bidirectional FK adjacency graph from declared FKs only.

    This is the runtime fallback when no precomputed join_graph.json exists.
    Returns:
        adj: lower_table_name → [(lower_neighbor, JoinEdge), ...]
        canonical: lower_table_name → canonical table name
    """
    adj: dict[str, list[tuple[str, JoinEdge]]] = {}
    canonical: dict[str, str] = {}

    for table in schema.tables:
        tl = table.name.lower()
        canonical[tl] = table.name
        adj.setdefault(tl, [])

        for fk in table.foreign_keys:
            rl = fk.ref_table.lower()
            edge = JoinEdge(
                src_table=table.name,
                src_col=fk.column,
                dst_table=fk.ref_table,
                dst_col=fk.ref_column,
                kind="declared",
            )
            adj[tl].append((rl, edge))
            adj.setdefault(rl, []).append((tl, edge))

    return adj, canonical


def _bfs_path(
    adj: dict[str, list[tuple[str, JoinEdge]]],
    src: str,
    dst: str,
) -> list[str] | None:
    """BFS shortest path (lowercased table names) from src to dst, or None."""
    if src == dst:
        return [src]
    visited = {src}
    queue: deque[tuple[str, list[str]]] = deque([(src, [src])])
    while queue:
        node, path = queue.popleft()
        for neighbor, _ in adj.get(node, []):
            if neighbor in visited:
                continue
            new_path = path + [neighbor]
            if neighbor == dst:
                return new_path
            visited.add(neighbor)
            queue.append((neighbor, new_path))
    return None


def _connected_components(
    tables_ci: set[str],
    adj: dict[str, list[tuple[str, JoinEdge]]],
) -> list[set[str]]:
    """Find connected components within the linked-tables-only FK subgraph."""
    visited: set[str] = set()
    components: list[set[str]] = []

    for start in sorted(tables_ci):
        if start in visited:
            continue
        component: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for neighbor, _ in adj.get(node, []):
                if neighbor in tables_ci and neighbor not in visited:
                    queue.append(neighbor)
        components.append(component)

    return components


def _discover_bridge_tables(
    tables: set[str],
    adj: dict[str, list[tuple[str, JoinEdge]]],
    canonical: dict[str, str],
) -> set[str]:
    """Find intermediate (bridge) tables needed to connect linked table pairs.

    Only searches for bridges between tables in DIFFERENT connected components
    of the linked-tables-only FK subgraph. Tables already transitively connected
    through other linked tables are skipped (avoids adding noise bridges).

    Returns set of canonical bridge table names (not already in `tables`).
    """
    tables_ci = {t.lower() for t in tables}
    bridges: set[str] = set()

    # Find connected components in the linked-tables-only subgraph
    components = _connected_components(tables_ci, adj)
    if len(components) <= 1:
        logger.debug("All %d linked tables already in one connected component", len(tables_ci))
        return bridges

    logger.info(
        "Bridge discovery: %d connected components among %d linked tables",
        len(components), len(tables_ci),
    )

    # BFS on the FULL graph between representatives of different components
    for i, comp_a in enumerate(components):
        for comp_b in components[i + 1:]:
            # Pick one representative from each component
            rep_a = min(comp_a)
            rep_b = min(comp_b)
            path = _bfs_path(adj, rep_a, rep_b)
            if path and len(path) > 2:
                for intermediate in path[1:-1]:
                    if intermediate not in tables_ci:
                        cname = canonical.get(intermediate, intermediate)
                        bridges.add(cname)
                        logger.info(
                            "Bridge discovery: adding table %s (connects %s ↔ %s)",
                            cname,
                            canonical.get(rep_a, rep_a),
                            canonical.get(rep_b, rep_b),
                        )
    return bridges


def _mst_edges(
    tables: set[str],
    adj: dict[str, list[tuple[str, JoinEdge]]],
) -> list[JoinEdge]:
    """Minimum spanning forest over linked tables (Kruskal's, all edges weight=1).

    Returns one representative FKEdge per table-pair in the spanning forest.
    """
    tables_ci = {t.lower() for t in tables}

    # Collect unique edges between linked table pairs
    seen_pairs: set[tuple[str, str]] = set()
    candidate_edges: list[JoinEdge] = []

    for tl in tables_ci:
        for neighbor, edge in adj.get(tl, []):
            if neighbor not in tables_ci:
                continue
            pair = (min(tl, neighbor), max(tl, neighbor))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                candidate_edges.append(edge)

    # Union-Find
    parent: dict[str, str] = {t: t for t in tables_ci}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    mst: list[JoinEdge] = []
    for edge in candidate_edges:
        if union(edge.src_table.lower(), edge.dst_table.lower()):
            mst.append(edge)

    return mst


_MAX_FKS_PER_REF = 2  # cap FK columns per (src_table → ref_table.ref_col) group


def _add_mst_columns(
    tables: set[str],
    columns: set[tuple[str, str]],
    adj: dict[str, list[tuple[str, JoinEdge]]],
) -> None:
    """Add FK+referenced columns along MST edges between linked tables.

    For each MST table pair, adds FK columns in both directions.  When
    multiple FK columns share the same (ref_table, ref_column) target
    (e.g. Match has 22 FKs all pointing to Player.player_api_id), only
    the first ``_MAX_FKS_PER_REF`` are kept.  This caps degenerate
    schemas while preserving semantically distinct FKs (home_team vs
    away_team, OwnerUserId vs LastEditorUserId).
    """
    tables_ci = {t.lower() for t in tables}

    # Find MST edges
    mst = _mst_edges(tables, adj)
    mst_pairs: set[tuple[str, str]] = set()
    for edge in mst:
        pair = (min(edge.src_table.lower(), edge.dst_table.lower()),
                max(edge.src_table.lower(), edge.dst_table.lower()))
        mst_pairs.add(pair)

    # Track how many FKs we've added per (src_table, ref_table, ref_col) group
    ref_group_count: dict[tuple[str, str, str], int] = {}

    for tl in tables_ci:
        for neighbor, edge in adj.get(tl, []):
            if neighbor not in tables_ci:
                continue
            pair = (min(tl, neighbor), max(tl, neighbor))
            if pair not in mst_pairs:
                continue
            # Cap per (src_table → dst_table.dst_col) group
            group_key = (edge.src_table.lower(), edge.dst_table.lower(), edge.dst_col.lower())
            count = ref_group_count.get(group_key, 0)
            if count >= _MAX_FKS_PER_REF:
                continue
            ref_group_count[group_key] = count + 1
            columns.add((edge.src_table, edge.src_col))
            columns.add((edge.dst_table, edge.dst_col))


def _add_linked_pks(
    original_tables: set[str],
    columns: set[tuple[str, str]],
    schema: DatabaseSchema,
) -> None:
    """Add PK columns from originally-linked tables (not bridge tables).

    PKs like ``cards.id`` or ``player.id`` are frequently used in gold SQL
    for GROUP BY, WHERE, and sub-selects even when no FK edge points at
    them.  Adding them only for the tables the linker already identified
    (not for bridge tables discovered by BFS) keeps noise low.
    """
    tables_ci = {t.lower() for t in original_tables}
    for table in schema.tables:
        if table.name.lower() not in tables_ci:
            continue
        for col in table.columns:
            if col.primary_key:
                columns.add((table.name, col.name))


def union_fields(
    all_extracted: list[ExtractedFields],
    schema: DatabaseSchema,
) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    """Union tables, columns, and literals across all extracted field sets.

    Resolves unqualified columns: for ("", col_name), search all schema tables
    for a matching column and add all matches (high-recall approach).
    """
    tables: set[str] = set()
    columns: set[tuple[str, str]] = set()
    literals: set[str] = set()

    # Build a case-insensitive lookup: lower(col_name) -> list of (table_name, real_col_name)
    col_to_tables: dict[str, list[tuple[str, str]]] = {}
    for t in schema.tables:
        for c in t.columns:
            col_to_tables.setdefault(c.name.lower(), []).append((t.name, c.name))

    for extracted in all_extracted:
        tables |= extracted.tables
        literals |= extracted.literals

        for table_ref, col_name in extracted.columns:
            if table_ref:
                columns.add((table_ref, col_name))
            else:
                # Unqualified — resolve against schema (case-insensitive)
                for tname, cname in col_to_tables.get(col_name.lower(), []):
                    columns.add((tname, cname))

    # Also add referenced tables from column qualifiers
    for table_ref, _ in columns:
        if table_ref:
            tables.add(table_ref)

    return tables, columns, literals


def add_join_paths(
    tables: set[str],
    columns: set[tuple[str, str]],
    schema: DatabaseSchema,
    use_bridge: bool = False,
    join_graph: JoinGraph | None = None,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Add join connectivity columns to the linked set.

    When *use_bridge* is False (default / legacy behaviour):
        - Adds ALL PK columns from every linked table (unconditional).
        - Adds FK columns that reference another already-linked table.

    When *use_bridge* is True (BFS bridge discovery + MST pruning):
        1. Loads the precomputed join graph (or builds from schema as fallback).
        2. BFS between disconnected components to discover bridge tables.
        3. Computes a minimum spanning forest over linked tables.
        4. Adds only FK + referenced columns along MST edges — no
           unconditional PK blast.

    Args:
        join_graph: Precomputed JoinGraph (declared + implicit FKs).
            If None, falls back to building from schema (declared FKs only).
    """
    if not use_bridge:
        return _add_join_paths_legacy(tables, columns, schema)

    pre_tables = set(tables)
    pre_cols = set(columns)

    if join_graph is not None:
        adj = join_graph.to_adjacency()
        canonical = dict(join_graph.canonical)
    else:
        adj, canonical = _build_fk_graph(schema)

    # Step 1: BFS bridge discovery — expand tables with intermediates
    bridges = _discover_bridge_tables(tables, adj, canonical)
    if bridges:
        tables |= bridges
        logger.info("Bridge discovery added %d tables: %s", len(bridges), sorted(bridges))

    # Step 2: MST-based column addition — only connectivity columns
    _add_mst_columns(tables, columns, adj)

    # Step 3: Add PKs from originally-linked tables (not bridges).
    # PKs are often used in gold SQL for GROUP BY / WHERE / sub-selects
    # even when they aren't on any FK edge.  Bridge tables only get MST
    # edge columns to keep noise low.
    _add_linked_pks(pre_tables, columns, schema)

    new_tables = tables - pre_tables
    new_cols = columns - pre_cols
    logger.info(
        "BFS+MST join paths: +%d tables, +%d columns (bridge mode)",
        len(new_tables), len(new_cols),
    )
    return tables, columns


def _add_join_paths_legacy(
    tables: set[str],
    columns: set[tuple[str, str]],
    schema: DatabaseSchema,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Legacy join path enrichment: all PKs + FKs to linked tables."""
    tables_ci = {t.lower() for t in tables}
    for table in schema.tables:
        if table.name.lower() not in tables_ci:
            continue

        # Always include PKs
        for col in table.columns:
            if col.primary_key:
                columns.add((table.name, col.name))

        # Include FK columns that connect this table to another linked table
        for fk in table.foreign_keys:
            if fk.ref_table.lower() in tables_ci:
                columns.add((table.name, fk.column))

    return tables, columns



def enrich_question_token_match(
    tables: set[str],
    columns: set[tuple[str, str]],
    schema: DatabaseSchema,
    question: str,
    evidence: str = "",
) -> set[tuple[str, str]]:
    """Match question/evidence tokens against column names in linked tables.

    Finds columns whose names overlap with words in the question. Uses
    2-gram matching to handle multi-word column names like 'first date',
    'school name', 'school type'.
    """
    import re

    tables_ci = {t.lower() for t in tables}
    added: set[tuple[str, str]] = set()

    # Tokenize question + evidence
    text = f"{question} {evidence}".lower()
    words = re.findall(r"[a-z]+", text)
    word_set = set(words)

    # Build 2-grams and 3-grams
    bigrams = {f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)}
    trigrams = {f"{words[i]} {words[i+1]} {words[i+2]}" for i in range(len(words) - 2)}
    all_ngrams = word_set | bigrams | trigrams

    for table in schema.tables:
        if table.name.lower() not in tables_ci:
            continue
        for col in table.columns:
            pair = (table.name, col.name)
            if pair in columns:
                continue
            col_lower = col.name.lower()
            # Exact match with n-gram
            if col_lower in all_ngrams:
                added.add(pair)
                columns.add(pair)

    if added:
        logger.info("Question-token match: added %d columns", len(added))
        for t, c in sorted(added):
            logger.debug("  Token match: %s.%s", t, c)
    return added


def render_pruned_schema(
    tables: set[str],
    columns: set[tuple[str, str]],
    schema: DatabaseSchema,
    profile: DatabaseProfile,
    bird_meta: "BirdMetadata | None" = None,
    join_graph: "JoinGraph | None" = None,
    use_quirks: bool = True,
) -> str:
    """Render only the linked tables/columns with short_summary (+ Bird CSV if available).

    When a column has a non-empty bird_enriched_summary (from the offline
    BirdEnricher pass), it replaces short_summary in the description line;
    this is how the --bird-enriched-profile flag takes effect at render time.
    use_quirks gates the quirks render block for ablation runs.
    """
    summaries: dict[str, dict[str, str]] = {}
    profile_stats: dict[str, dict[str, ColumnStats]] = {}
    profile_quirks: dict[str, dict[str, "ColumnQuirks"]] = {}  # noqa: F821
    for tp in profile.tables:
        summaries[tp.name] = {
            # bird_enriched_summary takes precedence when populated; it already
            # fuses BIRD docs + quirks + profiling, so the quirks render block
            # below becomes redundant gloss rather than primary information.
            cp.name: (cp.bird_enriched_summary or cp.short_summary)
            for cp in tp.columns
        }
        profile_stats[tp.name] = {cp.name: cp.stats for cp in tp.columns}
        profile_quirks[tp.name] = {cp.name: cp.quirks for cp in tp.columns}

    # Build case-insensitive lookup set for columns: {(lower_table, lower_col)}
    columns_ci = {(t.lower(), c.lower()) for t, c in columns}
    # Case-insensitive lookup set for tables
    tables_ci = {t.lower() for t in tables}

    lines: list[str] = []
    for table in sorted(schema.tables, key=lambda t: t.name):
        if table.name.lower() not in tables_ci:
            continue

        fk_map = {fk.column: (fk.ref_table, fk.ref_column) for fk in table.foreign_keys}
        pk_set = {col.name for col in table.columns if col.primary_key}

        col_lines: list[str] = []
        included_fks: list[tuple[str, str, str]] = []
        for col in table.columns:
            if (table.name.lower(), col.name.lower()) not in columns_ci:
                continue

            tags: list[str] = []
            if col.name in pk_set:
                tags.append("PK")
            if col.name in fk_map:
                ref_t, ref_c = fk_map[col.name]
                tags.append(f"FK → {ref_t}.{ref_c}")
                included_fks.append((col.name, ref_t, ref_c))
            tag_str = f", {', '.join(tags)}" if tags else ""

            desc_parts: list[str] = []
            quirks = profile_quirks.get(table.name, {}).get(col.name) if use_quirks else None
            # Priority 1: fuse short_summary + semantic_hint into one enriched description.
            # short_summary comes from profiling (stats-grounded). semantic_hint comes from
            # quirk enrichment (interpretive). Neither shadows the other — they concatenate.
            s = summaries.get(table.name, {}).get(col.name, "")
            hint = quirks.semantic_hint if quirks else ""
            if s and hint and hint not in s:
                desc_parts.append(f"{s} {hint}")
            elif s:
                desc_parts.append(s)
            elif hint:
                desc_parts.append(hint)
            # Priority 2: raw sample values — always kept when cardinality is low enough.
            stats = profile_stats.get(table.name, {}).get(col.name)
            if stats and stats.sample_values and stats.distinct_count <= 20:
                vals = ", ".join(repr(v) for v in stats.sample_values)
                desc_parts.append(f"Values: [{vals}]")
            # Priority 2b: quirk enum labels — additive gloss on top of raw values.
            if quirks and quirks.enum_labels:
                enum_str = ", ".join(
                    f"{k!r}→{v}" for k, v in quirks.enum_labels.items() if v and v != "unknown"
                )
                if enum_str:
                    desc_parts.append(f"Labels: {{{enum_str}}}")
            # Priority 3: quirk aliases (help LLM map user phrases → column).
            # Drop aliases that are trivial variants of the column name itself —
            # same string case-insensitive, or the whitespace/underscore swap —
            # since they add no signal over the column name already on the line.
            if quirks and quirks.aliases:
                col_lower = col.name.lower()
                col_spaced = col_lower.replace("_", " ")
                useful = [
                    a for a in quirks.aliases
                    if a.lower() != col_lower and a.lower() != col_spaced
                ]
                if useful:
                    desc_parts.append(f"Aliases: {', '.join(useful)}")
            # Priority 4: type mismatch warnings
            if quirks and quirks.type_mismatch:
                desc_parts.append(f"Note: {quirks.type_mismatch}")
            if bird_meta:
                b = bird_meta.get(table.name, col.name)
                if b and b not in desc_parts:
                    desc_parts.append(b)
            desc_str = f": {' | '.join(desc_parts)}" if desc_parts else ""

            col_lines.append(f'    - "{col.name}" ({col.type}{tag_str}){desc_str}')

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

    # Append join hubs from the precomputed JoinGraph (if provided).
    if join_graph is not None:
        hubs = render_join_hubs(tables, join_graph)
        if hubs:
            lines.append(hubs)

    bridge = bridge_tables_section(schema)
    if bridge:
        lines.append(bridge)

    return "\n".join(lines).rstrip()


def fallback_full_schema(
    schema: DatabaseSchema,
    profile: DatabaseProfile,
    bird_meta: "BirdMetadata | None" = None,
    join_graph: "JoinGraph | None" = None,
) -> SchemaLinkResult:
    """Return a SchemaLinkResult covering the full schema (linking fallback)."""
    from insightxpert_api.vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
    schema_text = SchemaFormatter(join_graph=join_graph).format(schema, profile, bird_meta=bird_meta)

    all_tables = [t.name for t in sorted(schema.tables, key=lambda t: t.name)]
    all_cols = [
        LinkedField(table=t.name, column=c.name)
        for t in sorted(schema.tables, key=lambda t: t.name)
        for c in t.columns
    ]
    return SchemaLinkResult(
        linked_tables=all_tables,
        linked_columns=all_cols,
        literals_found=[],
        variant_contributions={},
        schema_text=schema_text,
    )
