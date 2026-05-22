import pytest

from insightxpert_api.db.dialects import get_adapter
from insightxpert_api.db.dialects.base import UnknownDialectError


def test_get_adapter_sqlite():
    a = get_adapter("sqlite")
    assert a.name == "sqlite"


def test_get_adapter_postgres_registered():
    a = get_adapter("postgres")
    assert a.name == "postgres"


def test_get_adapter_bogus_raises():
    with pytest.raises(UnknownDialectError, match="bogus"):
        get_adapter("bogus")
