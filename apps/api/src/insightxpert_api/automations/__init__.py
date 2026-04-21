"""Phase C1 — Automations.

Ported from the public InsightXpert fork; ORM → SQLAlchemy Core, single-tenant,
no workflow canvas (C2 reservation via `workflow_graph_json` column only).

Gated by `settings.automations_enabled`. Dual-mode scheduler: embedded
APScheduler for local dev, external HMAC-signed endpoint for Cloud Run.
"""

from __future__ import annotations

__all__: list[str] = []
