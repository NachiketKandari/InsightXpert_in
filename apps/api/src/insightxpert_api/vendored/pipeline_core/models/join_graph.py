from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

JoinEdgeKind = Literal["declared", "value_verified", "rejected"]
JoinEdgeRejectReason = Literal["both_pk", "low_containment", "type_mismatch"]


class JoinEdge(BaseModel):
    """A join relationship between two tables.

    kind values:
      - "declared":       edge comes from a declared foreign key in the schema
      - "value_verified": implicit FK candidate whose values were confirmed via
                          a SQL containment check at profile time
      - "rejected":       implicit FK candidate that failed verification; retained
                          for audit but ignored by the render layer

    containment is populated whenever a containment ratio was computed
    (both value_verified and low_containment rejections).
    reason is populated for rejected edges.
    """

    src_table: str  # canonical table name (FK source / child side)
    src_col: str
    dst_table: str  # canonical table name (PK side)
    dst_col: str
    kind: JoinEdgeKind
    containment: float | None = None
    reason: JoinEdgeRejectReason | None = None


class JoinGraph(BaseModel):
    """Precomputed join graph for a database: declared FKs + implicit FK edges."""

    db_id: str
    canonical: dict[str, str]  # lower_name -> canonical table name
    edges: list[JoinEdge]

    def to_adjacency(self) -> dict[str, list[tuple[str, JoinEdge]]]:
        """Build bidirectional adjacency dict keyed by lowercase table names.

        Returns the same shape as linking_utils._build_fk_graph's adj dict.
        """
        adj: dict[str, list[tuple[str, JoinEdge]]] = {}
        for name_lower in self.canonical:
            adj[name_lower] = []
        for edge in self.edges:
            sl = edge.src_table.lower()
            dl = edge.dst_table.lower()
            adj.setdefault(sl, []).append((dl, edge))
            adj.setdefault(dl, []).append((sl, edge))
        return adj
