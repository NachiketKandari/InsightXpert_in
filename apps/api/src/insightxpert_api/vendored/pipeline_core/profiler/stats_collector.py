import logging

from insightxpert_api.vendored.pipeline_core.db import Database
from insightxpert_api.vendored.pipeline_core.models.profile import ColumnProfile, ColumnStats, DatabaseProfile, TableProfile
from insightxpert_api.vendored.pipeline_core.models.schema import ColumnSchema, DatabaseSchema, TableSchema

logger = logging.getLogger(__name__)

_SNOWFLAKE_UNORDERABLE = (
    "ARRAY", "VARIANT", "OBJECT", "STRUCT", "GEOGRAPHY", "GEOMETRY", "BINARY",
)

# Column types that store large opaque content — sampling their values is
# wasteful and can leak cross-database data (e.g. profile_json columns in a
# Supabase metadata DB contain profiles of unrelated databases).
_LARGE_CONTENT_TYPES = ("JSONB", "JSON", "BYTEA", "BLOB", "LONGTEXT", "MEDIUMTEXT")

# Name suffixes of columns that typically store structured/serialised data.
_LARGE_CONTENT_SUFFIXES = (
    "_json", "_encrypted", "_blob", "_payload", "_chunks", "_binary",
)


def _is_unorderable(col_type: str) -> bool:
    """True if the column type cannot be MIN/MAX/ORDER BY'd (Snowflake semi-structured)."""
    t = (col_type or "").upper()
    return any(t.startswith(u) or t == u for u in _SNOWFLAKE_UNORDERABLE)


def _should_skip_samples(col_name: str, col_type: str) -> bool:
    """True if this column likely stores large opaque content (JSON blobs,
    encrypted payloads, binary data) whose raw values are not useful as
    samples and could leak cross-database data."""
    t = (col_type or "").upper()
    if any(t.startswith(u) or t == u for u in _LARGE_CONTENT_TYPES):
        return True
    n = col_name.lower()
    return any(n.endswith(p) for p in _LARGE_CONTENT_SUFFIXES)


class StatsCollector:
    """Runs SQL queries against a database to gather per-column statistics."""

    def __init__(self, fast: bool = False) -> None:
        """fast=True: skip MIN/MAX/sample ORDER BY and use APPROX_COUNT_DISTINCT — safe on huge Snowflake tables."""
        self._fast = fast

    def collect(self, db: Database, schema: DatabaseSchema) -> DatabaseProfile:
        """Return a DatabaseProfile with raw stats for every column in the schema."""
        n_tables = len(schema.tables)
        _TABLE_LIMIT = 100
        skip_stats = self._fast and n_tables > _TABLE_LIMIT
        if skip_stats:
            logger.info(
                "Skipping per-table stats for '%s' (%d tables > %d): returning schema-only profile",
                schema.db_id, n_tables, _TABLE_LIMIT,
            )
            tables = [
                TableProfile(
                    name=t.name,
                    row_count=0,
                    columns=[
                        ColumnProfile(
                            name=c.name, type=c.type,
                            stats=ColumnStats(count=0, null_count=0, distinct_count=0),
                        )
                        for c in t.columns
                    ],
                )
                for t in schema.tables
            ]
            return DatabaseProfile(db_id=schema.db_id, tables=tables)

        logger.info("Collecting stats for '%s' (%d tables, fast=%s)", schema.db_id, n_tables, self._fast)
        tables: list[TableProfile] = []
        for t in schema.tables:
            if self._fast:
                tables.append(self._collect_table_batched(db, t))
            else:
                tables.append(self._collect_table(db, t))
        return DatabaseProfile(db_id=schema.db_id, tables=tables)

    def _collect_table(self, db: Database, table: TableSchema) -> TableProfile:
        """Collect row count and per-column stats for one table (one-query-per-column path)."""
        row_count = db.execute(f'SELECT COUNT(*) FROM "{table.name}"')[0][0]
        columns = [self._collect_column(db, table.name, col) for col in table.columns]
        logger.debug("  table '%s': %d rows, %d columns", table.name, row_count, len(columns))
        return TableProfile(name=table.name, row_count=row_count, columns=columns)

    def _collect_table_batched(self, db: Database, table: TableSchema) -> TableProfile:
        """Fast path: single scan per table, all aggregates for all columns in one query.
        Drops sample_values (quirk enrichment can work without them on Snowflake)."""
        select_parts: list[str] = ["COUNT(*)"]
        orderable: list[ColumnSchema] = []
        for col in table.columns:
            if _is_unorderable(col.type):
                select_parts.append(f'COUNT("{col.name}")')
                continue
            orderable.append(col)
            select_parts.extend([
                f'COUNT("{col.name}")',
                f'APPROX_COUNT_DISTINCT("{col.name}")',
                f'CAST(MIN("{col.name}") AS TEXT)',
                f'CAST(MAX("{col.name}") AS TEXT)',
            ])
        sql = f'SELECT {", ".join(select_parts)} FROM "{table.name}"'
        logger.info("  batched stats scan for '%s' (%d cols)...", table.name, len(table.columns))
        try:
            row = db.execute(sql)[0]
        except Exception as exc:
            logger.warning("Batched stats failed for %s, falling back to per-col: %s", table.name, exc)
            return self._collect_table(db, table)

        row_count = row[0]
        idx = 1
        columns: list[ColumnProfile] = []
        for col in table.columns:
            if _is_unorderable(col.type):
                count = row[idx]
                idx += 1
                columns.append(ColumnProfile(
                    name=col.name, type=col.type,
                    stats=ColumnStats(
                        count=count, null_count=row_count - count, distinct_count=0,
                        min_value=None, max_value=None, sample_values=[],
                    ),
                ))
                continue
            count, dcount, mn, mx = row[idx:idx + 4]
            idx += 4
            columns.append(ColumnProfile(
                name=col.name, type=col.type,
                stats=ColumnStats(
                    count=count, null_count=row_count - count, distinct_count=dcount,
                    min_value=mn, max_value=mx, sample_values=[],
                ),
            ))
        logger.info("  '%s': %d rows, %d columns done", table.name, row_count, len(columns))
        return TableProfile(name=table.name, row_count=row_count, columns=columns)

    def _collect_column(self, db: Database, table: str, col: ColumnSchema) -> ColumnProfile:
        """Run count/null/distinct/min/max/sample queries for a single column."""
        name = col.name
        complex_type = _is_unorderable(col.type)
        if self._fast:
            distinct_sql = f'SELECT APPROX_COUNT_DISTINCT("{name}") FROM "{table}"'
        else:
            distinct_sql = f'SELECT COUNT(DISTINCT "{name}") FROM "{table}"'

        count = null_count = distinct_count = 0
        min_val = max_val = None
        sample_values: list = []

        try:
            count = db.execute(f'SELECT COUNT("{name}") FROM "{table}"')[0][0]
            null_count = db.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{name}" IS NULL')[0][0]
            distinct_count = db.execute(distinct_sql)[0][0]
        except Exception as exc:
            logger.warning("Core stats failed for %s.%s: %s", table, name, exc)

        if not complex_type:
            try:
                min_val, max_val = db.execute(
                    f'SELECT CAST(MIN("{name}") AS TEXT), CAST(MAX("{name}") AS TEXT) FROM "{table}"'
                )[0]
            except Exception as exc:
                logger.debug("MIN/MAX failed for %s.%s: %s", table, name, exc)

            if not _should_skip_samples(name, col.type):
                try:
                    order_clause = "" if self._fast else f' ORDER BY "{name}"'
                    sample_values = [
                        r[0] for r in db.execute(
                            f'SELECT DISTINCT CAST("{name}" AS TEXT) FROM "{table}"'
                            f' WHERE "{name}" IS NOT NULL{order_clause} LIMIT 20'
                        )
                    ]
                except Exception as exc:
                    logger.debug("Sample values failed for %s.%s: %s", table, name, exc)

        return ColumnProfile(
            name=name,
            type=col.type,
            stats=ColumnStats(
                count=count,
                null_count=null_count,
                distinct_count=distinct_count,
                min_value=min_val,
                max_value=max_val,
                sample_values=sample_values,
            ),
        )
