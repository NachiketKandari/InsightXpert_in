from insightxpert_api.sample_questions.prompt_builder import build_prompt
from insightxpert_api.sample_questions.few_shot_retriever import FewShotExample
from insightxpert_api.vendored.pipeline_core.models.profile import (
    DatabaseProfile, TableProfile, ColumnProfile, ColumnStats,
)


def test_prompt_includes_schema_categories_and_examples():
    profile = DatabaseProfile(
        db_id="california_schools",
        tables=[
            TableProfile(name="schools", row_count=10, columns=[
                ColumnProfile(name="CDSCode", type="TEXT",
                              stats=ColumnStats(count=10, null_count=0, distinct_count=10)),
                ColumnProfile(name="County", type="TEXT",
                              stats=ColumnStats(count=10, null_count=0, distinct_count=5)),
            ]),
        ],
    )
    examples = [
        FewShotExample(db_id="x", category="Descriptive", features={}, question="How many rows?"),
        FewShotExample(db_id="x", category="Comparative", features={}, question="Which county is biggest?"),
        FewShotExample(db_id="x", category="Temporal", features={}, question="How did counts change over years?"),
    ]
    system, user = build_prompt(
        profile, ("Descriptive", "Comparative", "Temporal"), examples,
    )
    assert "Output strict JSON" in system
    assert "schools" in user
    assert "CDSCode" in user
    assert "Descriptive" in user and "Comparative" in user and "Temporal" in user
    assert "How many rows?" in user
    # No invented columns must appear
    assert "InventedCol" not in user
