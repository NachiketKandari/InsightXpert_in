"""Pydantic models for external DB connection configs.

Stored shape (in ``databases.connection_config_encrypted``): the JSON dump of
one of these models, encrypted via :mod:`connections.encryption`.

The ``kind`` discriminator matches the ``databases.kind`` column.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator, model_validator


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
    host: str = ""
    port: int = 1521
    service_name: str = ""
    # Owner/schema to introspect. Empty = the login user's own schema
    # (resolved server-side to username.upper()).
    schema_: str = Field(default="", alias="schema")
    username: str
    password: str
    # Subset of discovered tables to expose. None/empty = all tables.
    # Populated by the connect dialog's table picker; enforced at query time.
    selected_tables: list[str] | None = None
    # Raw connection string alternative to host/port/service_name. Either a
    # full TNS descriptor ``(DESCRIPTION=…)`` or an easy-connect string
    # ``host[:port][/service]``. Mutually exclusive with host/service_name.
    connection_string: str = ""

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _check_mode(self) -> OracleConnection:
        has_conn = bool(self.connection_string.strip())
        has_fields = bool(self.host.strip() or self.service_name.strip())
        if has_conn and has_fields:
            raise ValueError(
                "use either connection_string or host/service_name, not both"
            )
        if has_conn:
            _validate_oracle_connection_string(self.connection_string)
        else:
            if not self.host.strip():
                raise ValueError("host must not be empty")
            if not self.service_name.strip():
                raise ValueError("service_name must not be empty")
        return self

    def uses_descriptor(self) -> bool:
        """True when connection_string is a full ``(DESCRIPTION=…)`` TNS descriptor."""
        return self.connection_string.strip().startswith("(")

    def uses_connection_string(self) -> bool:
        return bool(self.connection_string.strip())

    def direct_dsn(self) -> str:
        """oracledb-native DSN for ``oracledb.connect(dsn=…)``.

        Full descriptors pass through untouched; easy-connect and structured
        configs normalize to ``host:port/service``.
        """
        if self.uses_descriptor():
            return self.connection_string.strip()
        if self.uses_connection_string():
            host, port, service = _parse_easy_connect(self.connection_string)
            return f"{host}:{port}/{service}"
        return f"{self.host.strip()}:{self.port}/{self.service_name.strip()}"

    def effective_schema(self) -> str:
        """Schema/owner to introspect: explicit ``schema`` or own schema."""
        return self.schema_.strip().upper() or self.username.strip().upper()

    def to_dsn(self) -> str:
        """SQLAlchemy URL for the ``oracle+oracledb`` dialect.

        Structured and easy-connect configs use the ``?service_name=`` query
        form (the URL path segment means SID to this dialect — not service).
        Full descriptors cannot be expressed as a plain URL, so they are
        carried in a ``?descriptor=`` marker URL understood by
        :mod:`insightxpert_api.db.dialects.oracle_url`; the SQLAlchemy engine
        path (``OracleConnector``) uses a ``creator`` callable instead and
        never parses this marker.
        """
        user = quote(self.username.strip(), safe="")
        pw = quote(self.password, safe="")
        if self.uses_descriptor():
            return (
                f"oracle+oracledb://{user}:{pw}@oracle-descriptor/"
                f"?descriptor={quote(self.connection_string.strip(), safe='')}"
            )
        if self.uses_connection_string():
            host, port, service = _parse_easy_connect(self.connection_string)
        else:
            host, port, service = (
                self.host.strip(),
                self.port,
                self.service_name.strip(),
            )
        return (
            f"oracle+oracledb://{user}:{pw}"
            f"@{quote(host, safe='')}:{port}/?service_name={quote(service, safe='')}"
        )


# Matches easy-connect strings: [//][user/pass@]host[:port][/service].
# Embedded credentials are rejected (username/password have their own fields).
_EASY_CONNECT_RE = re.compile(
    r"^(?://)?"
    r"(?P<host>[^/:@\s]+)"
    r"(?::(?P<port>\d+))?"
    r"(?:/(?P<service>[^/\s]+))?$"
)


def _parse_easy_connect(s: str) -> tuple[str, int, str]:
    """Split an easy-connect string into ``(host, port, service)``.

    Raises ``ValueError`` with user-facing guidance when the string has
    embedded credentials, no service, or is otherwise unparsable.
    """
    raw = s.strip()
    if "@" in raw:
        raise ValueError(
            "connection string must not contain credentials — "
            "put the username/password in their fields"
        )
    m = _EASY_CONNECT_RE.match(raw)
    if not m or not m.group("service"):
        raise ValueError(
            "connection string should look like host:1521/SERVICE "
            "or a full (DESCRIPTION=…) descriptor"
        )
    return (
        m.group("host"),
        int(m.group("port")) if m.group("port") else 1521,
        m.group("service"),
    )


def _validate_oracle_connection_string(s: str) -> None:
    """Validate the ``connection_string`` mode value. Raises ``ValueError``."""
    raw = s.strip()
    if raw.startswith("("):
        if "DESCRIPTION" not in raw.upper():
            raise ValueError("not a valid TNS descriptor (missing DESCRIPTION)")
        return
    _parse_easy_connect(raw)


