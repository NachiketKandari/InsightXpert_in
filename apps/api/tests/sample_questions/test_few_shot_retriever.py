from insightxpert_api.sample_questions.few_shot_retriever import (
    FewShotExample,
    pick_examples,
    load_bank,
)
from insightxpert_api.sample_questions.schema_features import SchemaFeatures


def _f(**o) -> SchemaFeatures:
    base = dict(
        has_temporal=False, has_categorical=True, has_numeric_metric=True,
        has_geo=False, has_relations=True, table_count=1, total_columns=2,
        total_rows=10, largest_table="t", first_numeric_metric="x",
        top_categorical_column="g",
    )
    base.update(o)
    return SchemaFeatures(**base)


def test_load_bank_non_empty():
    bank = load_bank()
    assert len(bank) >= 6
    assert all(isinstance(e, FewShotExample) for e in bank)


def test_pick_examples_returns_one_per_category():
    cats = ("Descriptive", "Comparative", "Temporal")
    out = pick_examples(_f(has_temporal=True), cats, exclude_db_id=None)
    assert [e.category for e in out] == list(cats)


def test_pick_examples_excludes_target_db():
    cats = ("Descriptive", "Comparative", "Temporal")
    out = pick_examples(_f(has_temporal=True), cats, exclude_db_id="california_schools")
    assert all(e.db_id != "california_schools" for e in out)


def test_pick_examples_falls_back_when_category_missing():
    # bank lacks Descriptive entries that exclude all dbs we know — still returns 3
    cats = ("Descriptive", "Comparative", "Segmentation")
    out = pick_examples(_f(), cats, exclude_db_id=None)
    assert len(out) == 3
