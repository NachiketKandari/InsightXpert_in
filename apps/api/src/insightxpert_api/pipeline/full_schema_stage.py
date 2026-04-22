"""FullSchemaStage — admin-selectable alternative to SchemaLinkerStage.

Bypasses trial-SQL / LSH / vector / join-path logic. Extracts a fresh
``DatabaseSchema`` (with FKs) from the SQLite file on disk via
``SchemaExtractor`` and calls the classical
``SchemaFormatter(join_graph=None).format(..., metadata_mode="profiling")``
to render the **complete** schema with FK tags inline + per-table
``Foreign Keys:`` blocks. The result is assigned to ``ctx.state["schema_text"]``
— the same key ``SqlGeneratorStage`` reads — so no downstream stages change.

One ``ChunkType.status`` chunk is emitted so the transparency UI can tell
this ran in place of the linker.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..services.database_service import DatabaseService
from ..sse.chunks import ChunkType, StatusPayload
from ..vendored.pipeline_core.db import SQLiteDatabase
from ..vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
from ..vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor
from .stage import PipelineContext

if TYPE_CHECKING:
    from ..vendored.pipeline_core.models.profile import DatabaseProfile
    from ..vendored.pipeline_core.models.schema import DatabaseSchema


class FullSchemaStage:
    """Stage that feeds the SQL generator the full `SchemaFormatter` render."""

    name = "full_schema"

    def __init__(self, db_svc: DatabaseService) -> None:
        self._db_svc = db_svc

    async def run(self, ctx: PipelineContext, _: object) -> dict[str, Any]:
        profile: DatabaseProfile = ctx.state["profile"]
        db_id: str = ctx.state.get("db_id", profile.db_id)
        # Prefer a fresh SchemaExtractor pass — it carries FKs from
        # PRAGMA foreign_key_list, which is what makes this mode worth using
        # over the linker's FK-stripped render. The profile's TableProfile
        # doesn't persist FKs, so we re-extract from the SQLite file.
        schema = ctx.state.get("schema") or self._extract_schema(ctx.session_id, db_id)

        schema_text = SchemaFormatter(join_graph=None).format(
            schema, profile, metadata_mode="profiling"
        )
        ctx.state["schema_text"] = schema_text

        # Emit an informational status chunk so the FE timeline can label the
        # run as full-schema (linker stage is intentionally absent).
        if ctx.emitter is not None:
            table_count = len(schema.tables)
            column_count = sum(len(t.columns) for t in schema.tables)
            await ctx.emitter.emit(
                ChunkType.STATUS,
                StatusPayload(
                    message=(
                        "pipeline_mode=full_schema — linker bypassed "
                        f"({table_count} tables, {column_count} columns)"
                    )
                ),
            )
        return {"schema_text": schema_text}

    def _extract_schema(self, session_id: str, db_id: str) -> "DatabaseSchema":
        """Fresh ``SchemaExtractor`` pass over the resolved SQLite file.

        The profile's ``TableProfile`` has no ``foreign_keys`` field, so we
        can't rebuild the schema from it with FK fidelity. Re-extracting from
        disk is cheap (a couple of PRAGMA calls) and is what makes this mode
        distinct from the linker (FK tags actually appear in the render).
        """
        ref = self._db_svc.resolve(session_id, db_id)
        if ref is None:
            raise ValueError(f"database not found: {db_id}")
        path = Path(ref.local_path)
        db = SQLiteDatabase(path)
        db.db_id = db_id
        with db:
            return SchemaExtractor().extract(db)
