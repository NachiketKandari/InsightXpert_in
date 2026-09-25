"""Pydantic models for external DB connection configs.

Stored shape (in ``databases.connection_config_encrypted``): the JSON dump of
one of these models, encrypted via :mod:`connections.encryption`.

The ``kind`` discriminator matches the ``databases.kind`` column.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator


class _RedactingMixin:
    """Override ``__repr__`` so secrets never leak into logs / error tracebacks."""

    def __repr__(self) -> str:  # type: ignore[override]
        d: dict[str, Any] = self.model_dump()  # type: ignore[attr-defined]
        for k in ("password", "auth_token"):
            if k in d and d[k]:
                d[k] = "***"
        return f"{self.__class__.__name__}({d})"


class PostgresConnection(_RedactingMixin, BaseModel):
    kind: Literal["postgres"] = "postgres"
    host: str
    port: int = 5432
    database: str
    username: str
    password: str
    ssl_mode: Literal["disable", "allow", "prefer", "require"] = "require"
    schema_: str = Field(default="public", alias="schema")

    model_config = {"populate_by_name": True}

    def to_dsn(self) -> str:
        pw = quote(self.password, safe="")
        return (
            f"postgresql+psycopg://{quote(self.username, safe='')}:{pw}"
            f"@{self.host}:{self.port}/{quote(self.database, safe='')}"
            f"?sslmode={self.ssl_mode}"
        )


class MySQLConnection(_RedactingMixin, BaseModel):
    kind: Literal["mysql"] = "mysql"
    host: str
    port: int = 3306
    database: str
    username: str
    password: str
    ssl_enabled: bool = True
    charset: str = "utf8mb4"

    def to_dsn(self) -> str:
        pw = quote(self.password, safe="")
        return (
            f"mysql+pymysql://{quote(self.username, safe='')}:{pw}"
            f"@{self.host}:{self.port}/{quote(self.database, safe='')}"
            f"?charset={self.charset}"
        )


class LibsqlConnection(_RedactingMixin, BaseModel):
    kind: Literal["libsql"] = "libsql"
    url: str
    auth_token: str

    @field_validator("url")
    @classmethod
    def _check_scheme(cls, v: str) -> str:
        if not v.startswith("libsql://"):
            raise ValueError("libsql URL must start with libsql://")
        return v


class OracleConnection(_RedactingMixin, BaseModel):
    kind: Literal["oracle"] = "oracle"
    host: str
    port: int = 1521
    service_name: str
    # Owner/schema to introspect. Empty = the login user's own schema
    # (resolved server-side to username.upper()).
    schema_: str = Field(default="", alias="schema")
    username: str
    password: str
    # Subset of discovered tables to expose. None/empty = all tables.
    # Populated by the connect dialog's table picker; enforced at query time.
    selected_tables: list[str] | None = None

    model_config = {"populate_by_name": True}

    @field_validator("service_name")
    @classmethod
    def _non_empty_service(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("service_name must not be empty")
        return v

    def effective_schema(self) -> str:
        """Schema/owner to introspect: explicit ``schema`` or own schema."""
        return self.schema_.strip().upper() or self.username.strip().upper()

    def to_dsn(self) -> str:
        pw = quote(self.password, safe="")
        return (
            f"oracle+oracledb://{quote(self.username, safe='')}:{pw}"
            f"@{self.host}:{self.port}/{quote(self.service_name, safe='')}"
        )


