"""Build a precomputed join graph (declared FKs + implicit FK edges) for a database.

Run once during profiling; the result is saved as join_graph.json and loaded
at query time to avoid rebuilding the FK adjacency graph per question.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinEdge, JoinGraph
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.db import Database

logger = logging.getLogger(__name__)

# Column names appearing in this many or more tables are considered generic
# (e.g. "name", "id", "type") and excluded from implicit FK discovery.
# Consistent with the threshold in schema_utils.bridge_tables_section.
_GENERIC_THRESHOLD = 3

_DEFAULT_CONTAINMENT_THRESHOLD = 0.9


def build_join_graph(
    schema: DatabaseSchema,
    db: "Database | None" = None,
    *,
    containment_threshold: float = _DEFAULT_CONTAINMENT_THRESHOLD,
) -> JoinGraph:
    """Build a JoinGraph with declared FKs + implicit FK edges.

    Implicit edges are discovered via column-name matching:
      - Two tables share a column name (case-insensitive)
      - At least one side has that column as a primary key
      - The column name is not generic (appears in < 3 tables)
      - No declared FK already covers this exact relationship

    If db is provided, implicit candidates are verified via SQL containment
    checks. Edges with ratio >= containment_threshold are emitted as
    kind="value_verified"; others as kind="rejected" with reason="low_containment".
    Without a db, all implicit candidates are rejected (containment=0.0).
    """
    canonical: dict[str, str] = {}
    for table in schema.tables:
        canonical[table.name.lower()] = table.name

    # --- Step A: Declared FK edges ---
    declared_edges: list[JoinEdge] = []
    declared_set: set[tuple[str, str, str, str]] = set()  # (src_lower, src_col_lower, dst_lower, dst_col_lower)

    for table in schema.tables:
        for fk in table.foreign_keys:
            edge = JoinEdge(
                src_table=table.name,
                src_col=fk.column,
                dst_table=fk.ref_table,
                dst_col=fk.ref_column,
                kind="declared",
            )
            declared_edges.append(edge)
            declared_set.add((
                table.name.lower(),
                fk.column.lower(),
                fk.ref_table.lower(),
                fk.ref_column.lower(),
            ))

    # --- Step B: Implicit FK discovery ---
    # Build col_name(lower) -> [(table_name, col_name, is_pk, type)]
    col_to_tables: dict[str, list[tuple[str, str, bool, str]]] = {}
    for table in schema.tables:
        pk_set = {c.name.lower() for c in table.columns if c.primary_key}
        for col in table.columns:
            cl = col.name.lower()
            col_to_tables.setdefault(cl, []).append(
                (table.name, col.name, cl in pk_set, col.type)
            )

    # Identify generic column names
    generic_names = {
        name for name, entries in col_to_tables.items()
        if len(entries) >= _GENERIC_THRESHOLD
    }

    implicit_edges: list[JoinEdge] = []
    for col_lower, entries in col_to_tables.items():
        if len(entries) < 2:
            continue

        # Check all pairs
        for i, (t1_name, c1_name, c1_pk, c1_type) in enumerate(entries):
            for t2_name, c2_name, c2_pk, c2_type in entries[i + 1:]:
                # Skip if a declared FK already covers this exact edge (either direction)
                key_fwd = (t1_name.lower(), c1_name.lower(), t2_name.lower(), c2_name.lower())
                key_rev = (t2_name.lower(), c2_name.lower(), t1_name.lower(), c1_name.lower())
                if key_fwd in declared_set or key_rev in declared_set:
                    continue

                # Both-PK → not an FK relationship; emit rejected edge for audit
                # (checked before generic-name filter so the audit record is always preserved)
                if c1_pk and c2_pk:
                    implicit_edges.append(JoinEdge(
                        src_table=t1_name, src_col=c1_name,
                        dst_table=t2_name, dst_col=c2_name,
                        kind="rejected", reason="both_pk",
                    ))
                    continue

                # Generic column names are excluded from FK discovery (but not from both-PK audit above)
                if col_lower in generic_names:
                    continue

                # Neither is a PK → not an FK candidate; skip silently (sibling children).
                if not c1_pk and not c2_pk:
                    continue

                # Type mismatch → reject without running SQL
                if _type_class(c1_type) != _type_class(c2_type):
                    # Orient arbitrarily for the rejection record
                    implicit_edges.append(JoinEdge(
                        src_table=t1_name, src_col=c1_name,
                        dst_table=t2_name, dst_col=c2_name,
                        kind="rejected", reason="type_mismatch",
                    ))
                    continue

                # Orient: PK side is dst, other is src (child)
                if c2_pk:
                    src_t, src_c = t1_name, c1_name
                    dst_t, dst_c = t2_name, c2_name
                else:
                    src_t, src_c = t2_name, c2_name
                    dst_t, dst_c = t1_name, c1_name

                ratio = _containment_ratio(db, src_t, src_c, dst_t, dst_c)

                if ratio is None:
                    # ratio unknown (no db, or child column has no non-null values) — reject as low_containment
                    implicit_edges.append(JoinEdge(
                        src_table=src_t, src_col=src_c,
                        dst_table=dst_t, dst_col=dst_c,
                        kind="rejected", reason="low_containment",
                        containment=0.0,
                    ))
                elif ratio >= containment_threshold:
                    implicit_edges.append(JoinEdge(
                        src_table=src_t, src_col=src_c,
                        dst_table=dst_t, dst_col=dst_c,
                        kind="value_verified", containment=ratio,
                    ))
                else:
                    implicit_edges.append(JoinEdge(
                        src_table=src_t, src_col=src_c,
                        dst_table=dst_t, dst_col=dst_c,
                        kind="rejected", reason="low_containment",
                        containment=ratio,
                    ))

    all_edges = declared_edges + implicit_edges
    n_declared = sum(1 for e in all_edges if e.kind == "declared")
    n_verified = sum(1 for e in all_edges if e.kind == "value_verified")
    n_rejected = sum(1 for e in all_edges if e.kind == "rejected")
    logger.info(
        "Join graph for %s: %d edges (%d declared, %d verified, %d rejected)",
        schema.db_id, len(all_edges), n_declared, n_verified, n_rejected,
    )
    return JoinGraph(db_id=schema.db_id, canonical=canonical, edges=all_edges)


def _type_class(sql_type: str) -> str:
    """Bucket a SQL type into integer/numeric/text/datetime/blob/other for compatibility checks.

    Follows SQLite type-affinity grouping broadly: DATE/DATETIME/TIMESTAMP are
    all treated as datetime (they can share values); BOOLEAN joins the integer
    bucket (stored as 0/1 under SQLite affinity).
    """
    t = sql_type.upper()
    if "INT" in t or "BOOL" in t:
        return "integer"
    if "REAL" in t or "FLOA" in t or "DOUB" in t or "NUM" in t or "DEC" in t:
        return "numeric"
    if "CHAR" in t or "TEXT" in t or "CLOB" in t:
        return "text"
    if "DATE" in t or "TIME" in t:
        return "datetime"
    if "BLOB" in t:
        return "blob"
    return "other"


def _containment_ratio(
    db: "Database | None",
    child_table: str,
    child_col: str,
    parent_table: str,
    parent_col: str,
) -> float | None:
    """Return |distinct(child) ∩ parent| / |distinct(child)|.

    Returns None when the ratio cannot be computed — either because no db handle
    was provided (verification disabled) or because the child column has zero
    non-null distinct values (nothing to measure). Callers treat either outcome
    as a rejection with reason='low_containment'.
    """
    if db is None:
        return None
    sql = (
        f'SELECT COUNT(*) AS total, COUNT(p."{parent_col}") AS matched '
        f'FROM (SELECT DISTINCT "{child_col}" AS v FROM "{child_table}" WHERE "{child_col}" IS NOT NULL) c '
        f'LEFT JOIN "{parent_table}" p ON p."{parent_col}" = c.v'
    )
    try:
        rows = db.execute(sql)
    except Exception as exc:  # noqa: BLE001 — isolate per-pair failures
        logger.warning(
            "Containment check failed for %s.%s → %s.%s: %s",
            child_table, child_col, parent_table, parent_col, exc,
        )
        return None
    if not rows:
        return None
    total, matched = rows[0]
    if not total:
        return None
    return matched / total
