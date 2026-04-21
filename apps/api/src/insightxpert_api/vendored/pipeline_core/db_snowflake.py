"""Snowflake database backend for Spider 2.0-Snow benchmark.

Uses snowflake-connector-python. Connection credentials come from .env
via config.Settings. Import is guarded so the package is only required
when actually using the spider_snow benchmark.
"""
import logging

try:
    import snowflake.connector as snowflake_connector
except ImportError:
    snowflake_connector = None  # type: ignore[assignment]

from insightxpert_api.vendored.pipeline_core.db import Database

logger = logging.getLogger(__name__)


class SnowflakeDatabase(Database):
    """Read-only Snowflake connection for benchmark evaluation."""

    def __init__(
        self,
        db_id: str,
        account: str,
        user: str,
        password: str,
        warehouse: str,
        database: str,
        schema: str = "PUBLIC",
    ) -> None:
        if snowflake_connector is None:
            raise ImportError(
                "snowflake-connector-python is required for spider_snow benchmark. "
                "Install with: uv pip install -e '.[snowflake]'"
            )
        self.db_id = db_id
        self._conn = snowflake_connector.connect(
            account=account,
            user=user,
            password=password,
            warehouse=warehouse,
            database=database,
            schema=schema,
        )
        self._active_schema = self._select_primary_schema(database) or schema
        if self._active_schema and self._active_schema != schema:
            self._conn.cursor().execute(f'USE SCHEMA "{database}"."{self._active_schema}"')
        try:
            self._conn.cursor().execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 600")
        except Exception as exc:
            logger.warning("Could not raise statement timeout: %s", exc)
        logger.info("Connected to Snowflake: %s/%s (timeout=600s)", database, self._active_schema)

    def _select_primary_schema(self, database: str) -> str | None:
        """Return the user schema with the most BASE TABLEs (ignoring PUBLIC unless it is the only one with tables)."""
        try:
            cur = self._conn.cursor()
            cur.execute(
                f"SELECT TABLE_SCHEMA, COUNT(*) AS n "
                f"FROM {database}.INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_TYPE = 'BASE TABLE' "
                "GROUP BY TABLE_SCHEMA ORDER BY n DESC"
            )
            rows = cur.fetchall()
        except Exception as exc:
            logger.warning("Schema probe failed for %s: %s", database, exc)
            return None
        non_public = [(s, n) for s, n in rows if s != "PUBLIC"]
        if non_public:
            return non_public[0][0]
        if rows:
            return rows[0][0]
        return None

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()

    def column_names(self, sql: str) -> list[str]:
        """Return column names for a query using cursor.description."""
        cur = self._conn.cursor()
        cur.execute(sql)
        if cur.description:
            return [d[0] for d in cur.description]
        return []

    def close(self) -> None:
        self._conn.close()
        logger.info("Snowflake connection closed: %s", self.db_id)
