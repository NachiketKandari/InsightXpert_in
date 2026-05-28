"""Shared MetaData so every Table registers under one namespace for Alembic.

DECISION(D-083): Plural module names for service groups (routes/, users/, databases/);
singular for single-concept domains (auth/, pipeline/, metrics/).
Files: table.py (schema), repository.py (data access), service.py (business logic).

DECISION(D-088): Google-style docstrings (Args/Returns/Raises) enforced by ruff.
"""

# DECISION(D-037): from __future__ import annotations — PEP 604 union syntax, forward references without quotes
from __future__ import annotations

from sqlalchemy import MetaData

# DECISION(D-013): SQLAlchemy Core (not ORM) — Table objects only on shared MetaData; no Session, no mapped classes
metadata = MetaData()
