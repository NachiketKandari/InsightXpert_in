"""DDL introspection — returns the CREATE statements for every table/view in a SQLite DB."""

from __future__ import annotations

import sqlite3


def ddl(path: str) -> str:
    """Return concatenated DDL for every user-defined table and view."""
    con = sqlite3.connect(path)
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
