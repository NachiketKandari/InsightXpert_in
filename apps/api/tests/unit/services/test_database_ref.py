from insightxpert_api.services.database_service import DatabaseRef


def test_sqlite_ref_has_dialect_default():
    ref = DatabaseRef(
        db_id="california_schools",
        source="bundled",
        local_path="/tmp/california_schools.sqlite",
    )
    assert ref.dialect == "sqlite"
    assert ref.connection_url is None
    assert ref.connection_url_env_var is None


def test_postgres_ref_has_no_local_path():
    ref = DatabaseRef(
        db_id="toxicology_pg",
        source="bundled",
        dialect="postgres",
        local_path=None,
        connection_url="postgresql://user:pw@host:5432/db",
        connection_url_env_var="DATABASE_URL_TOXICOLOGY_PG",
    )
    assert ref.dialect == "postgres"
    assert ref.local_path is None
    assert ref.connection_url is not None
