import pytest

from insightxpert_api.db.dialects import get_adapter


def test_postgres_adapter_registered():
    adapter = get_adapter("postgres")
    assert adapter.name == "postgres"
    assert adapter.sqlglot_dialect == "postgres"
    assert adapter.prompt_variant == "postgres"


@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET x=1",
    "DELETE FROM t",
    "TRUNCATE t",
    "COPY t FROM '/tmp/x.csv'",
    "GRANT ALL ON t TO postgres",
    "DROP SCHEMA x CASCADE",
    "ALTER TABLE t ADD COLUMN y INT",
    "REVOKE ALL ON t FROM PUBLIC",
])
def test_postgres_forbidden_regex_blocks(sql: str):
    adapter = get_adapter("postgres")
    assert adapter.forbidden_sql_re.search(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM t",
    "SELECT * FROM t WHERE name ILIKE 'foo%'",
    "SELECT date_trunc('day', created_at) FROM t",
    "SELECT * FROM t TABLESAMPLE SYSTEM (1) LIMIT 100",
])
def test_postgres_forbidden_regex_allows_reads(sql: str):
    adapter = get_adapter("postgres")
    assert not adapter.forbidden_sql_re.search(sql)


def test_postgres_profiling_queries_use_postgres_syntax():
    adapter = get_adapter("postgres")
    pack = adapter.profiling_queries()
    assert "FILTER" in pack.null_count.upper()
    assert "TABLESAMPLE" in pack.sample_rows.upper()


def test_postgres_is_timeout_error_classifies_queryCanceled():
    """Psycopg surfaces statement_timeout via psycopg.errors.QueryCanceled."""
    import psycopg
    adapter = get_adapter("postgres")
    # Build a minimal QueryCanceled instance — psycopg constructs these with a
    # diagnostic, but a bare instance is enough for isinstance-style classification.
    try:
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
    except psycopg.errors.QueryCanceled as e:
        assert adapter.is_timeout_error(e) is True
    assert adapter.is_timeout_error(ValueError("foo")) is False
