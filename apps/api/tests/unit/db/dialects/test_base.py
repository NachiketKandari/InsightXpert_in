import re

import pytest

from insightxpert_api.db.dialects.base import (
    DialectAdapter,
    ProfilingQueryPack,
    UnknownDialectError,
)


def test_protocol_is_importable():
    assert DialectAdapter is not None


def test_profiling_query_pack_fields():
    pack = ProfilingQueryPack(
        null_count="SELECT COUNT(*) FROM {table} WHERE {col} IS NULL",
        distinct_count="SELECT COUNT(DISTINCT {col}) FROM {table}",
        min_max="SELECT MIN({col}), MAX({col}) FROM {table}",
        sample_rows="SELECT {col} FROM {table} LIMIT 100",
    )
    assert "{table}" in pack.null_count
    assert "{col}" in pack.distinct_count


def test_unknown_dialect_error_is_exception():
    with pytest.raises(UnknownDialectError):
        raise UnknownDialectError("bogus")
