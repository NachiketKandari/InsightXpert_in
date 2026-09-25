"""Oracle connection-URL parsing shared by the dialect adapter paths.

``OracleConnection.to_dsn()`` produces one of three SQLAlchemy URL shapes:

* structured / easy-connect — ``oracle+oracledb://user:pass@host:port/?service_name=X``
* legacy SID path form — ``oracle+oracledb://user:pass@host:port/SID``
* full-descriptor marker — ``oracle+oracledb://user:pass@oracle-descriptor/?descriptor=<quoted>``

:func:`split_oracle_url` recovers ``(user, password, dsn)`` for
``oracledb.connect(user, password, dsn=…)`` from any of them, using
SQLAlchemy's own URL parser so adapter behavior matches the dialect.
``oracledb`` itself is only imported for the legacy SID branch.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote


def split_oracle_url(url: str) -> tuple[str, str, str]:
    """Return ``(user, password, dsn)`` for :func:`oracledb.connect`.

    Raises ``ValueError`` when the URL has no usable host/target.
    """
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")

    query: Any = parsed.query
    descriptor = query.get("descriptor")
    if descriptor:
        return user, password, unquote(descriptor)

    service = query.get("service_name")
    if service:
        return (
            user,
            password,
            f"{parsed.host}:{parsed.port or 1521}/{unquote(service)}",
        )

    database = parsed.database
    if database and parsed.host and parsed.host != "oracle-descriptor":
        import oracledb

        return (
            user,
            password,
            oracledb.makedsn(parsed.host, parsed.port or 1521, sid=database),
        )

    raise ValueError("unparsable Oracle connection URL (no service or descriptor)")
