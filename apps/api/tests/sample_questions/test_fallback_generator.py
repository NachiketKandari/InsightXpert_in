from insightxpert_api.sample_questions.fallback_generator import generate_fallback
from insightxpert_api.sample_questions.schema_features import SchemaFeatures


def _f(**o):
    base = dict(
        has_temporal=False, has_categorical=True, has_numeric_metric=True,
        has_geo=False, has_relations=False, table_count=1, total_columns=2,
        total_rows=10, largest_table="schools",
        first_numeric_metric="AvgScrMath", top_categorical_column="County",
    )
    base.update(o)
    return SchemaFeatures(**base)


def test_returns_three_categories_each_with_three_questions():
    out = generate_fallback(("Descriptive", "Comparative", "Segmentation"), _f())
    assert [c.name for c in out] == ["Descriptive", "Comparative", "Segmentation"]
    for c in out:
        assert len(c.questions) == 3
        for q in c.questions:
            assert q.endswith("?")


def test_includes_real_schema_names():
    out = generate_fallback(("Descriptive", "Comparative", "Segmentation"), _f())
    flat = " ".join(q for c in out for q in c.questions)
    assert "schools" in flat
    assert "AvgScrMath" in flat
    assert "County" in flat


def test_handles_missing_categorical_column():
    out = generate_fallback(
        ("Descriptive", "Segmentation", "Comparative"),
        _f(has_categorical=False, top_categorical_column=None),
    )
    for c in out:
        assert len(c.questions) == 3
