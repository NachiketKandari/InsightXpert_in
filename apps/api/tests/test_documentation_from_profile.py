"""Tests for the profile-driven business-context builder.

Replaces the previous hardcoded UPI ``DOCUMENTATION`` constant: the analyst's
system prompt now carries schema-derived context built from the active
``DatabaseProfile`` instead of someone else's pilot data.
"""

from __future__ import annotations

import pytest

from insightxpert_api.vendored.agents_core.training.documentation import (
    DOCUMENTATION,
    documentation_from_profile,
)
from insightxpert_api.vendored.pipeline_core.models.profile import (
    ColumnProfile,
    ColumnStats,
    DatabaseProfile,
    TableProfile,
)

# Tokens that must NEVER appear — these were in the old hardcoded constant.
LEAKED_DOMAIN_TOKENS = (
    "UPI",
    "fraud_flag",
    "Indian",
    "sender_state",
    "₹",
    "amount_inr",
    "Maharashtra",
)


def _stats(distinct: int = 5) -> ColumnStats:
    return ColumnStats(count=100, null_count=0, distinct_count=distinct)


def _column(name: str, type_: str, distinct: int = 5) -> ColumnProfile:
    return ColumnProfile(name=name, type=type_, stats=_stats(distinct))


def _two_table_profile() -> DatabaseProfile:
    return DatabaseProfile(
        db_id="california_schools",
        tables=[
            TableProfile(
                name="schools",
                row_count=17_686,
                columns=[
                    _column("cdscode", "TEXT", distinct=17_686),
                    _column("school", "TEXT", distinct=17_500),
                    _column("district", "TEXT", distinct=1_000),
                ],
            ),
            TableProfile(
                name="satscores",
                row_count=2_269,
                columns=[
                    _column("cds", "TEXT", distinct=2_269),
                    _column("avgscrread", "INTEGER", distinct=400),
                    _column("avgscrmath", "INTEGER", distinct=400),
                ],
            ),
        ],
    )


def test_default_constant_is_empty_fallback() -> None:
    """The old 60-line UPI block is gone — fallback is empty."""
    assert DOCUMENTATION == ""


def test_documentation_from_profile_lists_table_names() -> None:
    profile = _two_table_profile()
    rendered = documentation_from_profile(profile)

    assert "schools" in rendered
    assert "satscores" in rendered
    assert "california_schools" in rendered


def test_documentation_from_profile_under_length_cap() -> None:
    rendered = documentation_from_profile(_two_table_profile())
    assert len(rendered) < 1200, f"output too long: {len(rendered)} chars"


def test_documentation_from_profile_is_markdown() -> None:
    rendered = documentation_from_profile(_two_table_profile())
    assert rendered.startswith("## ")
    assert "## Tables" in rendered


def test_documentation_from_profile_no_domain_leakage() -> None:
    """No UPI/fraud_flag/sender_state tokens may appear in the output."""
    rendered = documentation_from_profile(_two_table_profile())
    for token in LEAKED_DOMAIN_TOKENS:
        assert token not in rendered, (
            f"profile-driven docs leaked '{token}' — "
            "the old hardcoded UPI block must be fully gone."
        )


def test_documentation_from_profile_includes_column_types() -> None:
    rendered = documentation_from_profile(_two_table_profile())
    # Spot-check that some column types surface so the LLM has real signal.
    assert "TEXT" in rendered
    assert "INTEGER" in rendered


def test_documentation_from_profile_handles_none() -> None:
    assert documentation_from_profile(None) == ""


def test_documentation_from_profile_handles_empty_profile() -> None:
    profile = DatabaseProfile(db_id="empty_db", tables=[])
    rendered = documentation_from_profile(profile)
    assert rendered  # not empty
    assert "empty_db" in rendered
    assert rendered.startswith("## ")


def test_documentation_from_profile_truncates_many_tables() -> None:
    """Profiles with 50+ tables list only the first ten and note the rest."""
    tables = [
        TableProfile(
            name=f"t{i:02d}",
            row_count=10,
            columns=[_column(f"c{i}", "INTEGER")],
        )
        for i in range(50)
    ]
    profile = DatabaseProfile(db_id="wide_db", tables=tables)
    rendered = documentation_from_profile(profile)

    assert "50 tables" in rendered
    assert "40 more" in rendered
    assert "`t00`" in rendered
    # Tables beyond the listed window must not be enumerated.
    assert "`t49`" not in rendered
    assert len(rendered) < 1200


@pytest.mark.parametrize("token", LEAKED_DOMAIN_TOKENS)
def test_module_constant_does_not_leak_domain(token: str) -> None:
    """Belt-and-suspenders: even the fallback constant carries no domain text."""
    assert token not in DOCUMENTATION
