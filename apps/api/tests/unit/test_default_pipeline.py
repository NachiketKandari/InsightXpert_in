"""Unit test for the ``default_pipeline`` factory.

Builds the pipeline with a dummy settings object + fake services and asserts
the stage order. Does not exercise any LLM — construction is enough.
"""
from __future__ import annotations

from dataclasses import dataclass

from insightxpert_api.pipeline import default_pipeline
from insightxpert_api.services.database_service import DatabaseService
from insightxpert_api.services.profile_service import ProfileService
from insightxpert_api.storage.local import LocalStorage


@dataclass
class _FakeSettings:
    gemini_api_key: str = "fake"
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    max_refinement_iterations: int = 2
    sql_row_limit: int = 1000


def test_default_pipeline_has_seven_ordered_stages(tmp_path):
    store = LocalStorage(str(tmp_path))
    db_svc = DatabaseService(bundled_dir=str(tmp_path / "bundled"), store=store)
    prof_svc = ProfileService(store)

    pipeline = default_pipeline(_FakeSettings(), db_svc, prof_svc)
    stages = pipeline.stages
    assert len(stages) == 7
    assert [s.name for s in stages] == [
        "profiler",
        "schema_linker",
        "sql_generator",
        "sql_validator",
        "sql_executor",
        "sql_refiner",
        "answer_synthesizer",
    ]
