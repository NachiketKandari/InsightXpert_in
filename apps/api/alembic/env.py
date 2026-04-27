"""Alembic environment. URL comes from app settings; target_metadata is our shared MetaData."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import every module that defines a Table so they register onto metadata
from insightxpert_api.config import get_settings
from insightxpert_api.db.base import metadata
from insightxpert_api.users import table as _users_table  # noqa: F401
from insightxpert_api.orchestration import table as _orch_tables  # noqa: F401
from insightxpert_api.audit import table as _audit_table  # noqa: F401
from insightxpert_api.metrics import table as _metrics_table  # noqa: F401
from insightxpert_api.databases import table as _databases_table  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# configparser interprets `%` as interpolation; escape so URL-encoded chars
# (e.g. `%40` for `@` in passwords) survive into the SQLAlchemy URL.
config.set_main_option(
    "sqlalchemy.url", get_settings().database_url.replace("%", "%%")
)

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
