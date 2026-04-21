"""Shared MetaData so every Table registers under one namespace for Alembic."""

from __future__ import annotations

from sqlalchemy import MetaData

metadata = MetaData()
