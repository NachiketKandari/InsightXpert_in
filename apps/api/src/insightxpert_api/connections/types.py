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


