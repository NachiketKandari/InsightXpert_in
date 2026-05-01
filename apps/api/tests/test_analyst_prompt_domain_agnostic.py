"""Regression tests guarding against domain leakage in the vendored analyst prompts.

The vendored agents_core prompts originated in a single-domain (Indian UPI
payments) pilot. insightxpert.ai is multi-domain — the user can connect any
SQLite database (BIRD bundles include schools, F1, toxicology, debit-card,
European football, financial, and transactions). These tests ensure the
prompt templates do not bake in payment-specific persona, schema, or citation
syntax that the FE has no infrastructure to render.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insightxpert_api.vendored.agents_core.prompts import render

# Tokens that must NOT appear in any rendered prompt — they would either
# mislead the LLM about the user's database (Indian/UPI/sender_state) or
# train it to emit citation markers the FE cannot render ([[1]], [[2]]).
LEAKED_DOMAIN_TOKENS = (
    "Indian",
    "UPI",
    "sender_state",
    "fraud_flag",
    "[[1]]",
    "[[2]]",
    "[[3]]",
    "[[N]]",
)

# Stricter token set for static-file scans (raw template source / Python source).
# Includes hardcoded Indian states, currency, and transaction-status enums that
# previously leaked through the vendored payments-domain pilot.
STRICT_LEAKED_TOKENS = (
    "fraud_flag",
    "fraud flag",
    "UPI",
    "sender_state",
    "Indian",
    "Maharashtra",
    "Uttar Pradesh",
    "Karnataka",
    "Tamil Nadu",
    "Gujarat",
    "Rajasthan",
    "West Bengal",
    "Andhra Pradesh",
    "Telangana",
    "Kerala",
    "PENDING",
    "Indian Rupees",
    "₹",  # ₹
    "amount_inr",
    "transaction_status",
)

FAKE_DDL = """
CREATE TABLE schools (
    cdscode TEXT PRIMARY KEY,
    school TEXT,
    district TEXT,
    county TEXT
);
CREATE TABLE satscores (
    cds TEXT,
    sname TEXT,
    avgscrread INTEGER,
    avgscrmath INTEGER
);
""".strip()

FAKE_DOCS = "California public schools and SAT score data, sourced from CDE."


@pytest.mark.parametrize(
    "template_name,kwargs",
    [
        (
            "analyst_system.j2",
            {
                "ddl": FAKE_DDL,
                "documentation": FAKE_DOCS,
                "similar_qa": [],
                "relevant_findings": [],
                "stats_context": None,
                "clarification_enabled": True,
            },
        ),
        (
            "response_generator.j2",
            {
                "ddl": FAKE_DDL,
                "documentation": FAKE_DOCS,
                "question": "Tell me about the schools.",
                "plan_reasoning": "Decomposed into temporal + comparative.",
                "evidence_data": "Source [1]: ...\nSource [2]: ...",
            },
        ),
        (
            "insight_synthesizer.j2",
            {
                "ddl": FAKE_DDL,
                "documentation": FAKE_DOCS,
                "question": "Tell me about the schools.",
                "analyst_sql": "SELECT 1",
                "results_summary": "1 row",
                "analyst_answer": "ok",
                "enrichment_data": "Source [2]: ...",
            },
        ),
        (
            "deep_synthesizer.j2",
            {
                "ddl": FAKE_DDL,
                "documentation": FAKE_DOCS,
                "question": "Tell me about the schools.",
                "why_intent": "compare",
                "dimensions_summary": "{}",
                "evidence_data": "Source [1]: ...",
            },
        ),
        (
            "investigation_synthesizer.j2",
            {
                "ddl": FAKE_DDL,
                "documentation": FAKE_DOCS,
                "question": "Tell me about the schools.",
                "evidence_data": "Source [1]: ...",
            },
        ),
        (
            "enrichment_evaluator.j2",
            {
                "ddl": FAKE_DDL,
                "documentation": FAKE_DOCS,
                "question": "Tell me about the schools.",
                "analyst_sql": "SELECT 1",
                "analyst_rows": [],
                "analyst_rows_summary": "no rows",
                "analyst_answer": "ok",
                "rag_context": [],
                "history": [],
                "max_tasks": 3,
            },
        ),
        (
            "dimension_extractor.j2",
            {
                "ddl": FAKE_DDL,
                "documentation": FAKE_DOCS,
                "question": "Tell me about the schools.",
                "history": [],
            },
        ),
        (
            "quant_analyst_system.j2",
            {"ddl": FAKE_DDL, "documentation": FAKE_DOCS},
        ),
        (
            "advanced_system.j2",
            {"ddl": FAKE_DDL, "documentation": FAKE_DOCS},
        ),
        (
            "insight_quality_evaluator.j2",
            {
                "question": "Tell me about the schools.",
                "synthesized_response": "...",
                "evidence_summary": "...",
            },
        ),
    ],
)
def test_prompt_is_domain_agnostic(template_name: str, kwargs: dict) -> None:
    """Render every vendored prompt and assert no payment-domain token leaks."""
    try:
        rendered = render(template_name, **kwargs)
    except Exception:
        # If a template requires kwargs we didn't supply, render with whatever
        # subset Jinja accepts. Jinja2's StrictUndefined isn't enabled, so
        # missing variables render as empty — the assertion below still holds.
        rendered = render(template_name)

    for token in LEAKED_DOMAIN_TOKENS:
        assert token not in rendered, (
            f"{template_name} leaks domain token '{token}'. "
            f"The vendored prompts must be domain-agnostic."
        )


# ---------------------------------------------------------------------------
# Static-file scans — guard non-vendored prompts and tool-description text
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
API_SRC = REPO_ROOT / "apps" / "api" / "src" / "insightxpert_api"

STATIC_SCAN_PATHS = (
    API_SRC / "prompts" / "answer_synthesizer.j2",
    API_SRC / "vendored" / "agents_core" / "prompts" / "statistician_system.j2",
)


@pytest.mark.parametrize("path", STATIC_SCAN_PATHS, ids=lambda p: p.name)
def test_static_prompt_file_has_no_domain_leak(path: Path) -> None:
    """Raw template files must not contain domain-specific leakage tokens."""
    assert path.exists(), f"Expected prompt file at {path}"
    text = path.read_text(encoding="utf-8")
    for token in STRICT_LEAKED_TOKENS:
        assert token not in text, (
            f"{path.name} contains leaked domain token '{token!r}'. "
            f"All prompts must be domain-agnostic."
        )


def test_advanced_tools_descriptions_have_no_domain_leak() -> None:
    """The argument-schema descriptions in advanced_tools.py must be neutral.

    These strings are sent to the LLM as part of tool definitions; any payments
    or Indian-domain leak there will train the model to assume that schema
    regardless of the user's actual database.
    """
    import re

    advanced_tools_path = (
        API_SRC / "vendored" / "agents_core" / "advanced_tools.py"
    )
    assert advanced_tools_path.exists()
    source = advanced_tools_path.read_text(encoding="utf-8")

    # Extract every "description": "..." string literal (single or multiline).
    description_pattern = re.compile(
        r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL
    )
    descriptions = description_pattern.findall(source)
    assert descriptions, "expected to find at least one description in advanced_tools.py"

    joined = "\n".join(descriptions)
    for token in STRICT_LEAKED_TOKENS:
        assert token not in joined, (
            f"advanced_tools.py tool descriptions leak domain token '{token!r}'. "
            f"Descriptions must use generic, schema-agnostic language."
        )
