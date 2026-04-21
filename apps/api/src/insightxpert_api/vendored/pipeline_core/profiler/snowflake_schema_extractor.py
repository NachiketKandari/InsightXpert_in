"""Schema extraction for Snowflake databases via INFORMATION_SCHEMA."""
import logging

from insightxpert_api.vendored.pipeline_core.db import Database
from insightxpert_api.vendored.pipeline_core.models.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKey,
    TableSchema,
)

logger = logging.getLogger(__name__)


class SnowflakeSchemaExtractor:
    """Extracts table/column/FK metadata from Snowflake via INFORMATION_SCHEMA."""

    def extract(self, db: Database, schema_name: str | None = None) -> DatabaseSchema:
        logger.debug("Extracting Snowflake schema from '%s'", db.db_id)
        if schema_name is None:
            active = getattr(db, "_active_schema", None)
            if active:
                schema_name = active
            else:
                row = db.execute("SELECT CURRENT_SCHEMA()")
                schema_name = row[0][0] if row else "PUBLIC"
        logger.info("Using schema '%s' for db '%s'", schema_name, db.db_id)
        tables = self._extract_tables(db, schema_name)
        fk_map = self._extract_all_foreign_keys(db, schema_name)

        for table in tables:
            table.foreign_keys = fk_map.get(table.name, [])

        total_cols = sum(len(t.columns) for t in tables)
        logger.debug(
            "Snowflake schema extracted: %d tables, %d columns, db_id='%s'",
            len(tables), total_cols, db.db_id,
        )
        return DatabaseSchema(db_id=db.db_id, tables=tables)

    def _extract_tables(self, db: Database, schema_name: str) -> list[TableSchema]:
        """Fetch all tables + columns in at most 2 queries (batched across all tables).

        Per-table column queries do not scale on Snowflake schemas with thousands of tables
        (e.g. GITHUB_REPOS_DATE has 5173 daily snapshot tables). PK detection is dropped
        because per-table SHOW PRIMARY KEYS is also O(N); downstream code tolerates no-PK.
        """
        rows = db.execute(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = %s "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (schema_name,),
        )
        by_table: dict[str, list[ColumnSchema]] = {}
        for table_name, col_name, col_type, nullable, _ord in rows:
            by_table.setdefault(table_name, []).append(
                ColumnSchema(
                    name=col_name,
                    type=col_type or "VARCHAR",
                    nullable=nullable == "YES",
                    primary_key=False,
                )
            )
        tables = [
            TableSchema(name=name, columns=cols, foreign_keys=[])
            for name, cols in sorted(by_table.items())
        ]
        return tables

    def _extract_primary_keys(self, db: Database, schema_name: str, table: str) -> set[str]:
        """Deprecated. Kept for backwards compatibility — returns empty."""
        return set()
        pk_cols: set[str] = set()
        for row in rows:
            if len(row) >= 5:
                pk_cols.add(row[4])
        return pk_cols

    def _extract_all_foreign_keys(self, db: Database, schema_name: str) -> dict[str, list[ForeignKey]]:
        """Best-effort FK extraction via SHOW IMPORTED KEYS. Falls back to empty on
        permission errors (PARTICIPANT role on shared Spider2 DBs lacks access to
        INFORMATION_SCHEMA constraint views)."""
        fk_map: dict[str, list[ForeignKey]] = {}
        try:
            rows = db.execute(f'SHOW IMPORTED KEYS IN SCHEMA "{schema_name}"')
        except Exception as exc:
            logger.debug("SHOW IMPORTED KEYS failed for %s: %s", schema_name, exc)
            return fk_map
        for row in rows:
            try:
                pk_table = row[3]
                pk_col = row[4]
                fk_table = row[7]
                fk_col = row[8]
            except (IndexError, TypeError):
                continue
            fk_map.setdefault(fk_table, []).append(
                ForeignKey(column=fk_col, ref_table=pk_table, ref_column=pk_col)
            )
        return fk_map
