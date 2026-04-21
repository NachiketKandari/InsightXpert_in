"""Shared helpers for rendering schema metadata sections (joinable columns, bridge tables)."""
from __future__ import annotations

import re

from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinGraph
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

_RANGE_MIN_ELEMENTS = 3  # require ≥3 contiguous numeric suffixes before compressing


def bridge_tables_section(schema: DatabaseSchema) -> str:
    """Detect bridge/junction tables and return a descriptive text block.

    A table is a bridge when most of its columns reference other tables
    (via declared FKs or matching column names) and it connects 2+ distinct tables.
    """
    num_tables = len(schema.tables)
    if num_tables < 2:
        return ""

    # Build lookup: col_name -> set of table names that have it
    col_to_tables: dict[str, set[str]] = {}
    for table in schema.tables:
        for col in table.columns:
            col_to_tables.setdefault(col.name, set()).add(table.name)

    # Exclude generic column names appearing in 3+ tables (likely data, not FK)
    generic_names = {
        name for name, tables in col_to_tables.items()
        if len(tables) >= 3
    }

    bridge_lines: list[str] = []
    for table in sorted(schema.tables, key=lambda t: t.name):
        if len(table.columns) < 2:
            continue

        fk_map = {fk.column: fk.ref_table for fk in table.foreign_keys}
        pk_set = {col.name for col in table.columns if col.primary_key}

        # For each column, find which other table(s) it references
        col_refs: dict[str, set[str]] = {}
        for col in table.columns:
            refs: set[str] = set()
            # Declared FK always counts (even if also a PK — composite FK/PK bridges)
            if col.name in fk_map:
                refs.add(fk_map[col.name])
            # Implicit FK via name match — only for non-PK columns (a PK being
            # referenced by others doesn't make this table a bridge)
            elif col.name not in pk_set and col.name not in generic_names:
                for other_table in col_to_tables.get(col.name, set()):
                    if other_table != table.name:
                        refs.add(other_table)
            col_refs[col.name] = refs

        referencing_cols = {c for c, refs in col_refs.items() if refs}
        total = len(table.columns)

        # Bridge: at most 1 column does NOT reference another table, and >= 2 do
        if len(referencing_cols) >= 2 and (total - len(referencing_cols)) <= 1:
            # Group columns by target table
            target_to_cols: dict[str, list[str]] = {}
            for col_name, refs in col_refs.items():
                for ref_table in refs:
                    target_to_cols.setdefault(ref_table, []).append(col_name)

            # Only report if bridging 2+ distinct tables
            if len(target_to_cols) >= 2:
                parts = []
                for target in sorted(target_to_cols):
                    cols_str = ", ".join(sorted(target_to_cols[target]))
                    parts.append(f"{target} (via {cols_str})")
                bridge_lines.append(f"  {table.name}: links {' ↔ '.join(parts)}")

    if not bridge_lines:
        return ""
    return "\nBridge Tables (many-to-many relationships):\n" + "\n".join(bridge_lines)


def _compress_numeric_suffixes(cols: list[str]) -> list[str]:
    """Collapse consecutive numeric-suffix columns into a ``prefix_N..M`` form.

    Only compresses when ≥3 columns share a common prefix AND their suffixes
    form a contiguous integer run. Otherwise returns columns individually.
    Example: ``home_player_1..11`` for away/home roster slots;
    ``atom_id`` and ``atom_id2`` stay separate (only 2 elements, below threshold).
    """
    prefix_nums: dict[str, list[int]] = {}
    non_numeric: list[str] = []
    for c in cols:
        m = re.match(r"^(.+?)(\d+)$", c)
        if m:
            prefix_nums.setdefault(m.group(1), []).append(int(m.group(2)))
        else:
            non_numeric.append(c)

    result = list(non_numeric)
    for prefix, nums in prefix_nums.items():
        uniq = sorted(set(nums))
        contiguous = len(uniq) >= _RANGE_MIN_ELEMENTS and (uniq[-1] - uniq[0] + 1) == len(uniq)
        if contiguous:
            result.append(f"{prefix}{uniq[0]}..{uniq[-1]}")
        else:
            result.extend(f"{prefix}{n}" for n in uniq)
    return sorted(result, key=str.lower)


def render_join_hubs(tables_in_scope: set[str], graph: JoinGraph) -> str:
    """Render an edge-per-line "Join edges" section from a JoinGraph.

    Format (one FK relationship per line, arrow points child → parent)::

        Join edges (verified, pick the one relevant to the question):
          child_table.child_col -> parent_table.parent_col
          ...

    Three noise-reduction rules:

    1. **Range compression** — when a child table has ≥3 contiguous
       numeric-suffix columns all pointing at the same parent column
       (e.g. ``home_player_1..11`` on a match roster), collapse to one line.
       ``atom_id, atom_id2`` stays on two lines (below threshold).
    2. **Pair trimming** — when the same (src_table, dst_table) pair has
       multiple candidate dst columns, keep only the edge whose dst column
       is most frequent across the verified graph; tie-break alphabetically.
    3. **Pass-through filter** — drop edges whose dst column is itself a
       declared FK src elsewhere (composite-PK/FK bridge columns are not
       true hubs).

    Ordering: high-degree parents (most incoming edges) first, alphabetical
    tie-break. Returns "" when no edges qualify.
    """
    scope_lower = {t.lower() for t in tables_in_scope}

    pass_through_cols: set[tuple[str, str]] = {
        (edge.src_table.lower(), edge.src_col.lower())
        for edge in graph.edges
        if edge.kind == "declared"
    }

    # Collect & dedup qualifying edges as (src_t, src_c, dst_t, dst_c) tuples.
    verified: set[tuple[str, str, str, str]] = set()
    for edge in graph.edges:
        if edge.kind not in ("declared", "value_verified"):
            continue
        if edge.src_table.lower() not in scope_lower:
            continue
        if edge.dst_table.lower() not in scope_lower:
            continue
        if (edge.dst_table.lower(), edge.dst_col.lower()) in pass_through_cols:
            continue
        verified.add((edge.src_table, edge.src_col, edge.dst_table, edge.dst_col))

    if not verified:
        return ""

    # Global column-name frequency across all kept edges (both src and dst
    # count, since a "common" column appears on both sides of many edges).
    col_freq: dict[str, int] = {}
    for st, sc, dt, dc in verified:
        col_freq[sc.lower()] = col_freq.get(sc.lower(), 0) + 1
        col_freq[dc.lower()] = col_freq.get(dc.lower(), 0) + 1

    # Pair trimming: for each (src_table, dst_table) pair, if multiple
    # dst_col options exist, keep only the highest-frequency one.
    pair_dst_options: dict[tuple[str, str], set[str]] = {}
    for st, sc, dt, dc in verified:
        pair_dst_options.setdefault((st.lower(), dt.lower()), set()).add(dc.lower())

    pair_winner: dict[tuple[str, str], str] = {}
    for pair, dst_cols in pair_dst_options.items():
        if len(dst_cols) > 1:
            pair_winner[pair] = sorted(
                dst_cols, key=lambda c: (-col_freq.get(c, 0), c)
            )[0]

    kept = {
        (st, sc, dt, dc)
        for (st, sc, dt, dc) in verified
        if (st.lower(), dt.lower()) not in pair_winner
        or dc.lower() == pair_winner[(st.lower(), dt.lower())]
    }

    # Group by (dst_table, dst_col) for hub-degree ordering, then by src_table
    # for per-parent child listing. Child-column sets are range-compressed.
    by_parent: dict[tuple[str, str], dict[str, list[str]]] = {}
    for st, sc, dt, dc in kept:
        by_parent.setdefault((dt, dc), {}).setdefault(st, []).append(sc)

    # Sort parents by total incoming edge count (degree), alphabetically on ties.
    sorted_parents = sorted(
        by_parent.items(),
        key=lambda kv: (-sum(len(v) for v in kv[1].values()), kv[0][0].lower(), kv[0][1].lower()),
    )

    lines = ["\nJoin edges (verified, pick the one relevant to the question):"]
    for (dt, dc), by_src in sorted_parents:
        for st in sorted(by_src.keys(), key=str.lower):
            for src_col in _compress_numeric_suffixes(by_src[st]):
                lines.append(f"  {st}.{src_col} -> {dt}.{dc}")
    return "\n".join(lines)
