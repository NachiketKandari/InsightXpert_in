"""`databases` + `database_shares` tables (SQLAlchemy Core).

Visibility is one of 'private' (owner-only), 'shared' (owner + named users via
database_shares), or 'public' (all users). Bundled BIRD DBs are seeded as
visibility='public' with owner_user_id=NULL in the migration.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    String,
    Table,
)

from ..db.base import metadata

databases_table = Table(
    "databases",
    metadata,
    Column("db_id", String(255), primary_key=True),
    Column("owner_user_id", String(36), nullable=True),
    Column("visibility", String(16), nullable=False),
    Column("size_bytes", Integer, nullable=True),
    Column("created_at", Integer, nullable=False),
    # Tier-1 full-schema mode: per-DB override. NULL = inherit system default
    # (currently "linked"). Values: "linked" | "full_schema".
    Column("pipeline_mode_default", String(32), nullable=True),
    # BYO-DB connector: 'sqlite_file' (bundled / uploaded on-disk SQLite),
    # 'libsql' (Turso URL we own — post-v1), 'sqlite_external' (libSQL URL the
    # user owns — post-v1), 'postgres' (BYO Postgres). The connector dispatch
    # in db/connector.py uses this column to pick the right backend.
    Column("kind", String(32), nullable=False, server_default="sqlite_file"),
    # Encrypted JSON config blob (Fernet). Shape depends on `kind`:
    #   postgres → {host,port,database,username,password,ssl_mode,schema}
    #   libsql   → {url, auth_token}
    # Decrypted only at query time via connections.encryption.decrypt.
    Column("connection_config_encrypted", String, nullable=True),
    CheckConstraint(
        "visibility IN ('private','shared','public')",
        name="databases_visibility_check",
    ),
    CheckConstraint(
        "kind IN ('sqlite_file','libsql','sqlite_external','postgres')",
        name="databases_kind_check",
    ),
)

database_shares = Table(
    "database_shares",
    metadata,
    Column("db_id", String(255), primary_key=True),
    Column("user_id", String(36), primary_key=True),
    Column("created_at", Integer, nullable=False),
)
