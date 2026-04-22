from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "src" / "insightxpert_api" / "prompts"
    / "sql_generation_postgres.j2"
)


def test_postgres_prompt_file_exists():
    assert PROMPT_PATH.exists(), f"Missing {PROMPT_PATH}"


def test_postgres_prompt_has_postgres_indicators():
    text = PROMPT_PATH.read_text()
    assert "PostgreSQL" in text
    # At least one of these Postgres-specific markers must appear:
    assert any(m in text for m in ["ILIKE", "::", "TO_CHAR", "DATE_TRUNC"])
    # And it must tell the model not to use backticks (common LLM error):
    assert "backtick" in text.lower() or "double-quoted" in text.lower()
