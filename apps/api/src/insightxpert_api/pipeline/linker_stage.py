"""SchemaLinkerStage — single-prompt schema linking for v1.

Emits fine-grained SSE events so the UI can render the "which signals pulled
which columns" transparency required by the design spec. The composition mirrors
the vendored ``SinglePromptLinker.link`` but keeps the stage's external contract
minimal (no BIRD metadata, no join-graph). Few-shot retrieval is handled in
the route's preflight (see ``services/few_shot_service.py``); the chosen
example sits at ``ctx.state["few_shot_example"]`` and is consumed by
``SqlGeneratorStage`` rather than this stage.

Steps (each emits its own SSE chunk):
  1. ``schema_linking_started``
  2. call LLM with the clean prompt → parse 5 fenced SQL blocks → ``candidate_sqls_generated``
  3. literal matching via LSH (optional, skipped if no index) → ``literals_extracted``
  4. semantic top-k from vector index (optional) → ``semantic_matches``
  5. join paths added (declared FKs) → ``join_paths_added``
  6. render final linked schema → ``linked_schema_final``
"""

from __future__ import annotations

import pickle
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Template

from ..llm import LLMProvider
from ..sse.chunks import (
    CandidateSQLsGeneratedPayload,
    ChunkType,
    JoinEdgePayload,
    JoinPathsAddedPayload,
    LinkedSchemaFinalPayload,
    LiteralsExtractedPayload,
    SchemaLinkingStartedPayload,
    SemanticMatchesPayload,
    SemanticMatchPayload,
)
from ..vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
from ..vendored.pipeline_core.linker.linking_utils import add_join_paths, union_fields
from ..vendored.pipeline_core.linker.literal_matcher import LiteralMatcher
from ..vendored.pipeline_core.linker.trial_query import TrialQueryGenerator
from .stage import PipelineContext

if TYPE_CHECKING:
    from ..vendored.pipeline_core.models.profile import DatabaseProfile
    from ..vendored.pipeline_core.models.schema import DatabaseSchema

_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)


class SchemaLinkerStage:
    """Wraps single-prompt schema linking as a ``Stage``."""

    name = "schema_linker"

    def __init__(
        self,
        llm: LLMProvider,
        prompt_path: str,
        vector_index_path: str | None = None,
        lsh_index_path: str | None = None,
        join_graph_path: str | None = None,
    ) -> None:
        self._llm = llm
        self._tpl = Template(Path(prompt_path).read_text())
        self._vector_index_path = vector_index_path
        self._lsh_index_path = lsh_index_path
        self._join_graph_path = join_graph_path

    async def run(self, ctx: PipelineContext, _: object) -> dict[str, Any]:
        question: str = ctx.state["question"]
        profile: DatabaseProfile = ctx.state["profile"]
        db_id: str = ctx.state.get("db_id", profile.db_id)
        schema: DatabaseSchema = ctx.state.get("schema") or self._extract_schema(ctx)

        await self._emit(
            ctx,
            ChunkType.SCHEMA_LINKING_STARTED,
            SchemaLinkingStartedPayload(question=question, db_id=db_id),
        )

        schema_text_full = SchemaFormatter().format(schema, profile, metadata_mode="profiling")
        prompt = self._tpl.render(question=question, evidence="", schema_text=schema_text_full)
        raw = await self._llm.async_generate(prompt)

        candidates = [m.strip().rstrip(";").strip() for m in _FENCE_RE.findall(raw)]
        await self._emit(
            ctx,
            ChunkType.CANDIDATE_SQLS_GENERATED,
            CandidateSQLsGeneratedPayload(candidates=candidates),
        )

        # 1. Extract fields from each candidate.
        all_extracted = []
        for sql in candidates:
            ef = TrialQueryGenerator._parse_fields(sql)
            ef.sql = sql
            all_extracted.append(ef)
        tables, columns, all_literals = union_fields(all_extracted, schema)

        column_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
        for tc in columns:
            column_sources[tc].add("trial_sql")

        # 2. LSH literal matching (best-effort).
        literal_matches: dict[str, list[str]] = {}
        lsh_index = self._load_lsh()
        if lsh_index is not None and all_literals:
            matcher = LiteralMatcher(lsh_index)
            matched, _unmatched, literal_to_cols = matcher.match_detailed(all_literals)
            literal_matches = literal_to_cols
            for t, c in matched:
                tables.add(t)
                columns.add((t, c))
                column_sources[(t, c)].add("literal_lsh")
        await self._emit(
            ctx,
            ChunkType.LITERALS_EXTRACTED,
            LiteralsExtractedPayload(
                literals=sorted(all_literals), matches=literal_matches
            ),
        )

        # 3. Semantic top-k from vector index.
        semantic: list[SemanticMatchPayload] = []
        vec_index = self._load_vector_index()
        if vec_index is not None:
            try:
                q_emb = self._llm.embed(question) if hasattr(self._llm, "embed") else None
                if q_emb:
                    for col_id, score in vec_index.search(q_emb, top_k=10):
                        if score > 0.5:
                            parts = col_id.split(".", 1)
                            if len(parts) == 2:
                                tables.add(parts[0])
                                columns.add((parts[0], parts[1]))
                                column_sources[(parts[0], parts[1])].add("semantic")
                                semantic.append(
                                    SemanticMatchPayload(column=col_id, score=float(score))
                                )
            except Exception:  # pragma: no cover — best-effort
                pass
        await self._emit(
            ctx,
            ChunkType.SEMANTIC_MATCHES,
            SemanticMatchesPayload(matches=semantic),
        )

        # 4. Add declared-FK join paths.
        pre_cols = set(columns)
        tables, columns = add_join_paths(tables, columns, schema, use_bridge=False)
        edges: list[JoinEdgePayload] = []
        for t, c in columns - pre_cols:
            column_sources[(t, c)].add("join_path")
        for t in schema.tables:
            if t.name not in tables:
                continue
            for fk in t.foreign_keys:
                if fk.ref_table in tables:
                    edges.append(
                        JoinEdgePayload(
                            **{"from": f"{t.name}.{fk.column}"},
                            to=f"{fk.ref_table}.{fk.ref_column}",
                            kind="declared",
                        )
                    )
        await self._emit(
            ctx,
            ChunkType.JOIN_PATHS_ADDED,
            JoinPathsAddedPayload(edges=edges),
        )

        # 5. Render final linked schema.
        serialized_sources = {
            f"{t}.{c}": sorted(srcs) for (t, c), srcs in sorted(column_sources.items())
        }
        schema_text = self._render_linked(schema, profile, tables, columns)

        final_payload = LinkedSchemaFinalPayload(
            schema_text=schema_text,
            linked_tables=sorted(tables),
            linked_columns=sorted(f"{t}.{c}" for t, c in columns),
            column_sources=serialized_sources,
        )
        await self._emit(ctx, ChunkType.LINKED_SCHEMA_FINAL, final_payload)

        result = {
            "schema_text": schema_text,
            "linked_tables": sorted(tables),
            "linked_columns": sorted(f"{t}.{c}" for t, c in columns),
            "column_sources": serialized_sources,
        }
        ctx.state["schema_text"] = schema_text
        ctx.state["column_sources"] = serialized_sources
        ctx.state["linked_tables"] = result["linked_tables"]
        ctx.state["linked_columns"] = result["linked_columns"]
        return result

    # ---- helpers ---------------------------------------------------------

    def _extract_schema(self, ctx: PipelineContext) -> DatabaseSchema:
        """Re-derive schema from the profile — minimal metadata is enough."""
        from ..vendored.pipeline_core.models.schema import (
            ColumnSchema,
            DatabaseSchema,
            TableSchema,
        )
        profile: DatabaseProfile = ctx.state["profile"]
        tables = []
        for tp in profile.tables:
            tables.append(
                TableSchema(
                    name=tp.name,
                    columns=[
                        ColumnSchema(
                            name=cp.name,
                            type=cp.type,
                            nullable=True,
                            primary_key=False,
                        )
                        for cp in tp.columns
                    ],
                    foreign_keys=[],
                )
            )
        return DatabaseSchema(db_id=profile.db_id, tables=tables)

    def _load_lsh(self):
        if not self._lsh_index_path:
            return None
        p = Path(self._lsh_index_path)
        if not p.exists():
            return None
        try:
            with open(p, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None

    def _load_vector_index(self):
        if not self._vector_index_path:
            return None
        p = Path(self._vector_index_path)
        if not p.exists():
            return None
        try:
            from ..vendored.pipeline_core.profiler.vector_builder import VectorIndex
            cols_path = p.parent / "vector_columns.json"
            return VectorIndex.load(p, cols_path)
        except Exception:
            return None

    @staticmethod
    def _render_linked(
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        tables: set[str],
        columns: set[tuple[str, str]],
    ) -> str:
        """Minimal renderer: linked tables + their linked columns + types."""
        col_types: dict[tuple[str, str], str] = {}
        for t in schema.tables:
            for c in t.columns:
                col_types[(t.name, c.name)] = c.type
        lines: list[str] = []
        for tname in sorted(tables):
            cols = sorted(c for t, c in columns if t == tname)
            if not cols:
                continue
            lines.append(f'Table: "{tname}"')
            lines.append("  Columns:")
            for cname in cols:
                ctype = col_types.get((tname, cname), "TEXT")
                lines.append(f'    - "{cname}" ({ctype})')
        return "\n".join(lines)

    @staticmethod
    async def _emit(ctx: PipelineContext, chunk_type: ChunkType, payload: Any) -> None:
        if ctx.emitter is None:
            return
        await ctx.emitter.emit(chunk_type, payload)
