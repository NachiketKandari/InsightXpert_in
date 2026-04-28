from insightxpert_api.sample_questions.category_selector import select_categories
from insightxpert_api.sample_questions.schema_features import SchemaFeatures


def _f(**overrides) -> SchemaFeatures:
    base = dict(
        has_temporal=False, has_categorical=False, has_numeric_metric=False,
        has_geo=False, has_relations=False, table_count=1, total_columns=1,
        total_rows=10, largest_table="t", first_numeric_metric=None,
        top_categorical_column=None,
    )
    base.update(overrides)
    return SchemaFeatures(**base)


def test_temporal_categorical_path():
    assert select_categories(_f(has_temporal=True, has_categorical=True)) == (
        "Descriptive", "Comparative", "Temporal",
    )


def test_no_temporal_with_categorical():
    assert select_categories(_f(has_categorical=True)) == (
        "Descriptive", "Comparative", "Segmentation",
    )


def test_no_categorical_no_temporal_with_numeric_falls_back_to_segmentation_then_comparative():
    # has_categorical False → slot2 = Segmentation; slot3 = Correlation (needs both)
    # neither → slot3 = Comparative (universal last resort)
    assert select_categories(_f()) == (
        "Descriptive", "Segmentation", "Comparative",
    )


def test_numeric_plus_categorical_no_temporal_picks_correlation_third():
    assert select_categories(_f(has_categorical=True, has_numeric_metric=True)) == (
        "Descriptive", "Comparative", "Segmentation",
    )


def test_only_temporal_no_categorical():
    assert select_categories(_f(has_temporal=True)) == (
        "Descriptive", "Segmentation", "Temporal",
    )
