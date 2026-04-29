"""Build the SYSTEM + USER messages for the sample-questions LLM call."""
from __future__ import annotations

from typing import Sequence

from ..vendored.pipeline_core.models.profile import DatabaseProfile
from .few_shot_retriever import FewShotExample
from .types import CategoryName

SYSTEM = (
    "You generate starter analytical questions for a database.\n"
    'Output strict JSON: {"categories":[{"name":..., "questions":[...]}, ...]}.\n'
    "Exactly 3 categories in the order given. Exactly 3 questions per category.\n"
    "Each question is one sentence, ends with \"?\", references real column or "
    "table names from the schema, and is answerable by a single SQL query.\n"
    "Avoid duplicates and near-duplicates. Avoid columns not in the schema."
)


def _render_schema(profile: DatabaseProfile) -> str:
    lines: list[str] = []
    for t in profile.tables:
        cols = ", ".join(f"{c.name} {c.type}" for c in t.columns)
        lines.append(f"- {t.name}({cols})")
    return "\n".join(lines)


def build_prompt(
    profile: DatabaseProfile,
    categories: Sequence[CategoryName],
    examples: Sequence[FewShotExample],
) -> tuple[str, str]:
    total_rows = sum(t.row_count for t in profile.tables)
    schema = _render_schema(profile)
    cats_line = ", ".join(categories)
    example_lines = "\n".join(f"[{e.category}] {e.question}" for e in examples)

    user = (
        f"Database: {profile.db_id}  ({len(profile.tables)} tables, {total_rows} rows)\n\n"
        f"Schema (compact):\n{schema}\n\n"
        f"Categories to use (in order): {cats_line}\n\n"
        f"Few-shot examples of strong questions in this style:\n{example_lines}\n\n"
        "Generate the JSON now."
    )
    return SYSTEM, user
