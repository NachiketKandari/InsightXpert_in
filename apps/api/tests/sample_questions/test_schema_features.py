from insightxpert_api.sample_questions.schema_features import (
    SchemaFeatures,
    extract_features,
)
from insightxpert_api.vendored.pipeline_core.models.profile import (
    DatabaseProfile,
    TableProfile,
    ColumnProfile,
    ColumnStats,
)


def _col(name: str, type_: str, distinct: int = 5, null: int = 0, count: int = 100):
    return ColumnProfile(
        name=name,
        type=type_,
        stats=ColumnStats(count=count, null_count=null, distinct_count=distinct),
    )


def _profile(tables: list[TableProfile]) -> DatabaseProfile:
    return DatabaseProfile(db_id="t", tables=tables)


def test_temporal_detected_by_type():
    p = _profile([TableProfile(name="t", row_count=100, columns=[
        _col("created_at", "TIMESTAMP"),
    ])])
    f = extract_features(p)
    assert f.has_temporal is True


def test_temporal_detected_by_name_only():
    p = _profile([TableProfile(name="t", row_count=100, columns=[
        _col("event_year", "INTEGER"),
    ])])
    assert extract_features(p).has_temporal is True


def test_categorical_detected():
    p = _profile([TableProfile(name="t", row_count=200, columns=[
        _col("status", "TEXT", distinct=4, count=200),
    ])])
    assert extract_features(p).has_categorical is True


def test_no_categorical_when_high_cardinality():
    p = _profile([TableProfile(name="t", row_count=200, columns=[
        _col("name", "TEXT", distinct=180, count=200),
    ])])
    assert extract_features(p).has_categorical is False


def test_numeric_metric_detected():
    p = _profile([TableProfile(name="t", row_count=10, columns=[
        _col("amount", "REAL"),
    ])])
    assert extract_features(p).has_numeric_metric is True


def test_geo_detected_by_name():
    p = _profile([TableProfile(name="t", row_count=10, columns=[
        _col("country", "TEXT"),
    ])])
    assert extract_features(p).has_geo is True


def test_largest_table_picked():
    p = _profile([
        TableProfile(name="small", row_count=10, columns=[_col("x", "INT")]),
        TableProfile(name="big", row_count=1000, columns=[_col("y", "INT")]),
    ])
    assert extract_features(p).largest_table == "big"
