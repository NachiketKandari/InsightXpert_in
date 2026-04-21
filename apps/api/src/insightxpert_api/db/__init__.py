"""Database access layer: read-only SQLite connector + schema introspection."""

from .connector import DatabaseConnector, ForbiddenSQLError, QueryResult, SQLTimeoutError
from .schema import ddl

__all__ = [
    "DatabaseConnector",
    "ForbiddenSQLError",
    "QueryResult",
    "SQLTimeoutError",
    "ddl",
]
