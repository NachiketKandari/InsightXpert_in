"""Business context for the analyst's system prompt.

Originally upstream this module hard-coded a 60+ line description of an
Indian-UPI payments dataset (the upstream pilot domain). insightxpert.ai is
multi-domain — every connected database has a different schema — so the
hardcoded constant would silently inject UPI/fraud_flag/sender_state context
into the LLM's system prompt regardless of which database the user selected.

This file is intentionally diverged from upstream:

* ``DOCUMENTATION`` is now an empty fallback used only when no profile-derived
  business context is available.
* ``documentation_from_profile`` builds a short markdown overview from a live
  ``DatabaseProfile`` so the prompt automatically describes the user's
  actual schema instead of someone else's pilot data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile

# Empty fallback. Used only when the chat dispatcher couldn't load a profile
# (e.g. profiling hasn't run yet, or the route forgot to pass an override).
DOCUMENTATION = ""

# Hard cap for builder output. The system prompt also carries DDL + few-shots,
# so business context needs to stay tight.
_MAX_LENGTH = 1200
_MAX_TABLES_LISTED = 10
_MAX_NOTABLE_COLS = 4


def documentation_from_profile(profile: "DatabaseProfile | None") -> str:
    """Render a short markdown business-context doc from a profile.

    The output describes the active database in domain-neutral terms — table
    names, row counts, primary keys, and a few notable columns per table —
    so the analyst's system prompt has *some* context for the user's actual
    schema instead of the previous hardcoded UPI block.

    Pure function. Returns an empty string for ``None`` and a minimal valid
    markdown stub for an empty profile (``db_id`` set, no tables) so the
    caller never has to special-case missing data.
    """
    if profile is None:
        return ""

    tables = list(profile.tables or [])
    db_id = profile.db_id or "unknown"

    if not tables:
        return f"## Database Overview\n\nDatabase `{db_id}` has no profiled tables yet."

    lines: list[str] = ["## Database Overview", ""]

    listed = tables[:_MAX_TABLES_LISTED]
    listed_names = ", ".join(f"`{t.name}`" for t in listed)
    overflow = len(tables) - len(listed)
    if overflow > 0:
        lines.append(
            f"Database `{db_id}` contains {len(tables)} tables: "
            f"{listed_names}, and {overflow} more."
        )
    else:
        lines.append(
            f"Database `{db_id}` contains {len(tables)} "
            f"table{'s' if len(tables) != 1 else ''}: {listed_names}."
        )

    lines.append("")
    lines.append("## Tables")
    lines.append("")

    for tp in listed:
        col_count = len(tp.columns)

        # Pick a stable, useful subset of columns: the first column with the
        # highest distinct_count (proxy for likely PK / identifier) plus a few
        # additional columns from the head of the column list.
        notable: list[str] = []
        seen: set[str] = set()

        if tp.columns:
            try:
                pk_like = max(
                    tp.columns,
                    key=lambda c: getattr(c.stats, "distinct_count", 0) or 0,
                )
                notable.append(f"`{pk_like.name}` ({pk_like.type})")
                seen.add(pk_like.name)
            except ValueError:
                pass

        for col in tp.columns:
            if len(notable) >= _MAX_NOTABLE_COLS:
                break
            if col.name in seen:
                continue
            notable.append(f"`{col.name}` ({col.type})")
            seen.add(col.name)

        notable_str = ", ".join(notable) if notable else "(no columns profiled)"
        lines.append(
            f"- **`{tp.name}`** — {tp.row_count} rows, {col_count} "
            f"column{'s' if col_count != 1 else ''}. Notable columns: {notable_str}."
        )

    result = "\n".join(lines).rstrip()

    # Hard cap. Truncate at a line boundary to avoid leaving a half-rendered
    # markdown bullet, and mark the truncation so downstream readers know.
    if len(result) > _MAX_LENGTH:
        truncated = result[:_MAX_LENGTH]
        cut = truncated.rfind("\n")
        if cut > 0:
            truncated = truncated[:cut]
        result = truncated.rstrip() + "\n\n_…overview truncated._"

    return result
