"""DDL introspection — returns the CREATE statements for every table/view in a database.

Routes connection-open through the dialect adapter so callers don't hardcode sqlite3.
"""

from __future__ import annotations

from typing import Any

from .dialects import get_adapter


def ddl(ref: Any) -> str:
    """Return concatenated DDL for every user-defined table and view.

    ``ref`` is a DatabaseRef (Any-typed to avoid circular import).

    For SQLite: queries sqlite_master for CREATE statements directly.
    For Postgres: delegates to adapter.extract_schema() + DDL rendering.
      NOTE — PostgresAdapter.extract_schema() is not yet implemented (lands in
      Task 10). The Postgres branch raises NotImplementedError intentionally;
      this is a planned stub per the Phase B implementation plan.
    """
    adapter = get_adapter(ref.dialect)

    if ref.dialect == "sqlite":
        con = adapter.open_readonly(ref)
        try:
            rows = con.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type IN ('table','view') AND sql IS NOT NULL "
                "ORDER BY name"
            ).fetchall()
        finally:
            con.close()
        statements = [row[0].rstrip(";") for row in rows if row and row[0]]
        return ";\n\n".join(statements) + (";" if statements else "")

    # --- Postgres (and any other future dialect) ---
    # Intentional stub: PostgresAdapter.extract_schema() + DDL rendering land in Task 10.
    # Until then, calling ddl() on a non-SQLite ref raises NotImplementedError so
    # callers fail fast rather than silently return empty DDL.
    raise NotImplementedError(
        f"DDL rendering for dialect {ref.dialect!r} is not yet implemented "
        "(PostgresAdapter.extract_schema lands in Task 10)"
    )
