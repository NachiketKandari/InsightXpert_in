"""Canonical forbidden-SQL regex — the single source of truth for write-statement
detection across ALL SQL execution paths.

Three regex variants composed from the same base keyword list:

* ``FORBIDDEN_SQL_RE`` — word-boundary match against all common DDL/DML keywords.
  Used by the dialect adapters (postgres.py, sqlite.py) and the PostgresConnector.
* ``FORBIDDEN_SQL_WITH_PRAGMA_RE`` — ``FORBIDDEN_SQL_RE`` plus a ``PRAGMA ... =``
  clause. Used only by the SQLite adapter (where PRAGMA writes are meaningful).
* ``FORBIDDEN_SQL_PREFIX_RE`` — anchored-at-start variant. Kept for backward
  compat with vendored/agents_core/sql_guard.py which historically used
  prefix-only matching. New code should prefer the word-boundary variant.

Maintenance rule: when adding a keyword, add it to ``_KEYWORDS`` below — all
three exported regexes pick it up automatically.
"""

from __future__ import annotations

import re

# Sorted alphabetically for mergability; each keyword is wrapped in \b…\b by
# _build_re().  Additions must be SQL keywords that could mutate data or schema.
_KEYWORDS = [
    "ALTER",
    "ANALYZE",
    "ATTACH",
    "CALL",
    "CREATE",
    "DELETE",
    "DETACH",
    "DISCARD",
    "DO",
    "DROP",
    "GRANT",
    "INSERT",
    "LOCK",
    "MERGE",
    "REINDEX",
    "REPLACE",
    "REVOKE",
    "SECURITY\\s+DEFINER",
    "SET",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
]


def _build_re(*, prefix_only: bool = False) -> re.Pattern[str]:
    """Compile the keyword list into a single alternation regex.

    Args:
        prefix_only: If True, anchor at ``^\\s*`` (only matches keywords at the
            very start of the SQL string).  If False, use ``\\b`` word-boundary
            matching (catches keywords anywhere in the string).
    """
    if prefix_only:
        return re.compile(
            r"^\s*(" + "|".join(_KEYWORDS) + r")\b",
            re.IGNORECASE,
        )

    alt = "|".join(_KEYWORDS)
    return re.compile(
        r"\b(" + alt + r")\b"
        r"|"
        r"\bCOPY\b\s+\S+\s+\bFROM\b"  # COPY table FROM …
        r"|"
        r"\bSELECT\b\s+.+\s+\bINTO\b",  # SELECT … INTO (creates tables)
        re.IGNORECASE,
    )


# Primary regex — catches write keywords anywhere in the SQL via \b word boundaries.
FORBIDDEN_SQL_RE: re.Pattern[str] = _build_re(prefix_only=False)

# SQLite-specific: adds PRAGMA … = pattern on top of the primary regex.
FORBIDDEN_SQL_WITH_PRAGMA_RE: re.Pattern[str] = re.compile(
    FORBIDDEN_SQL_RE.pattern + r"|(?:\bPRAGMA\s+\w+\s*=)",
    re.IGNORECASE,
)

# Prefix-only variant — kept for backward compat with vendored code that
# historically used ^\s* anchoring.  Still uses the canonical keyword list;
# just doesn't scan past the first token.
FORBIDDEN_SQL_PREFIX_RE: re.Pattern[str] = _build_re(prefix_only=True)
