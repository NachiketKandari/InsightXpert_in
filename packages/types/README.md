# @insightxpert/types

Shared TypeScript types mirroring the backend's Pydantic contracts. Imported by `apps/web` so the FE and BE cannot drift on wire shapes.

v1 is **hand-curated** — small surface, easy to keep in sync by eye. When the type footprint grows, swap this file for JSON-Schema-driven codegen off the FastAPI OpenAPI dump.

Source of truth is `apps/api/src/insightxpert_api/sse/chunks.py` and the route response models.
