"""Verify SqlGeneratorStage picks the correct prompt variant via DialectAdapter."""
from __future__ import annotations

from unittest.mock import MagicMock

from insightxpert_api.db.dialects import get_adapter
from insightxpert_api.pipeline import generator_stage


def test_sqlite_variant_is_sqlite():
    assert get_adapter("sqlite").prompt_variant == "sqlite"


def test_postgres_variant_is_postgres():
    assert get_adapter("postgres").prompt_variant == "postgres"




def test_prompt_name_for_dialect_sqlite():
    assert generator_stage._prompt_name_for_dialect("sqlite") == "sql_generation"


def test_prompt_name_for_dialect_postgres():
    assert generator_stage._prompt_name_for_dialect("postgres") == "sql_generation_postgres"
