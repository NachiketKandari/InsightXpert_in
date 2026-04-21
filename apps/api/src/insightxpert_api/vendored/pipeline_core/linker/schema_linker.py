"""Schema linking orchestrator: union linked fields across 5 schema variants."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.linker.few_shot_retriever import FewShotRetriever
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile
from insightxpert_api.vendored.pipeline_core.models.query import FewShotExampleRef, LinkedField, SchemaLinkResult
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
from insightxpert_api.vendored.pipeline_core.profiler.lsh_builder import LSHIndex
from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorIndex
from insightxpert_api.vendored.pipeline_core.linker.linking_utils import (
    add_join_paths as _add_join_paths_util,
    fallback_full_schema as _fallback_full_schema_util,
    render_pruned_schema as _render_pruned_schema_util,
    union_fields as _union_fields_util,
)
from insightxpert_api.vendored.pipeline_core.linker.literal_matcher import LiteralMatcher
from insightxpert_api.vendored.pipeline_core.linker.schema_formatter import SchemaVariantFormatter
from insightxpert_api.vendored.pipeline_core.linker.trial_query import ExtractedFields, TrialQueryGenerator

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinGraph
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)

_VARIANT_NAMES = [
    "full_schema",
    "minimal_profile",
    "maximal_profile",
    "focused_schema",
    "full_profile",
]


class SchemaLinker:
    """Orchestrates the 5-variant schema linking algorithm from the paper (Section 3)."""

    def __init__(
        self,
        llm: BaseLLM,
        lsh_index: LSHIndex,
        vector_index: VectorIndex | None = None,
        use_literal_revision: bool = False,
        use_bridge_join: bool = False,
        join_graph: "JoinGraph | None" = None,
        use_quirks: bool = True,
        few_shot_retriever: FewShotRetriever | None = None,
    ) -> None:
        self._llm = llm
        self._lsh = lsh_index
        self._vector_index = vector_index
        self._use_literal_revision = use_literal_revision
        self._use_bridge_join = use_bridge_join
        self._join_graph = join_graph
        self._use_quirks = use_quirks
        self._few_shot_retriever = few_shot_retriever
        self._formatter = SchemaVariantFormatter()
        self._trial_gen = TrialQueryGenerator(llm)
        self._literal_matcher = LiteralMatcher(lsh_index)

    def _enrich_few_shot(
        self, db_id: str, question: str, schema: DatabaseSchema,
    ) -> tuple[set[tuple[str, str]], FewShotExampleRef | None]:
        """Retrieve top-1 few-shot example and resolve its columns to canonical schema names."""
        if self._few_shot_retriever is None:
            return set(), None
        example = self._few_shot_retriever.retrieve(db_id, question)
        if example is None:
            return set(), None

        canon: dict[tuple[str, str], tuple[str, str]] = {}
        for t in schema.tables:
            for c in t.columns:
                canon[(t.name.lower(), c.name.lower())] = (t.name, c.name)

        resolved: set[tuple[str, str]] = set()
        dropped = 0
        for tbl, col in example.columns:
            if not tbl:
                continue
            mapped = canon.get((tbl.lower(), col.lower()))
            if mapped is None:
                dropped += 1
                continue
            resolved.add(mapped)
        if dropped:
            logger.debug(
                "few-shot: %d columns from retrieved example don't exist in db_id=%s schema (skipped)",
                dropped, db_id,
            )

        ref = FewShotExampleRef(
            question=example.question,
            gold_sql=example.gold_sql,
            similarity=example.similarity,
        )
        return resolved, ref

    def link(
        self,
        question: str,
        evidence: str,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        bird_meta: "BirdMetadata | None" = None,
        db_id: str = "",
        **kwargs: object,
    ) -> SchemaLinkResult:
        """Run schema linking and return a pruned SchemaLinkResult.

        Generates 5 trial SQL queries across schema representation variants,
        extracts referenced fields via sqlglot, matches string literals via LSH,
        and returns the union of all linked fields.
        """
        variants = self._generate_variants(question, evidence, schema, profile)
        all_extracted: list[tuple[str, ExtractedFields]] = []
        variant_contributions: dict[str, int] = {}
        cumulative_cols: set[tuple[str, str]] = set()

        for name in _VARIANT_NAMES:
            schema_text = variants[name]
            logger.info("Schema linking: trial SQL for variant '%s'", name)
            extracted = self._trial_gen.generate_and_extract(
                question, evidence, schema_text, variant_name=name
            )

            if self._use_literal_revision and extracted.literals:
                extracted = self._revise_literals(
                    extracted, question, evidence, schema_text, name
                )

            all_extracted.append((name, extracted))

            new_cols = extracted.columns - cumulative_cols
            variant_contributions[name] = len(new_cols)
            cumulative_cols |= extracted.columns
            logger.debug(
                "Variant '%s': +%d new columns (total so far: %d)",
                name, len(new_cols), len(cumulative_cols),
            )

        tables, columns, all_literals = self._union_fields(all_extracted, schema)

        # LSH literal matching
        literal_cols = self._literal_matcher.match(all_literals)
        for table_name, col_name in literal_cols:
            tables.add(table_name)
            columns.add((table_name, col_name))

        # Add PK/FK join-path columns for every linked table
        tables, columns = self._add_join_paths(tables, columns, schema)

        # Few-shot retrieval: union the retrieved example's gold-SQL columns
        few_shot_cols, few_shot_ref = self._enrich_few_shot(db_id, question, schema)
        new_from_few_shot = few_shot_cols - columns
        for t, c in few_shot_cols:
            tables.add(t)
            columns.add((t, c))
        if few_shot_ref is not None:
            logger.info(
                "few-shot merged into linked schema: cols_from_example=%d new=%d",
                len(few_shot_cols), len(new_from_few_shot),
            )

        if not columns:
            logger.warning("Schema linking produced zero columns; falling back to full schema")
            return self._fallback_full_schema(schema, profile, bird_meta, self._join_graph)

        pruned_text = self._render_pruned_schema(tables, columns, schema, profile, bird_meta, self._join_graph)

        total_cols = sum(len(t.columns) for t in schema.tables)
        logger.info(
            "Schema linking done: %d/%d tables, %d/%d columns linked",
            len(tables), len(schema.tables),
            len(columns), total_cols,
        )

        linked_columns = [
            LinkedField(table=t, column=c) for t, c in sorted(columns)
        ]
        return SchemaLinkResult(
            linked_tables=sorted(tables),
            linked_columns=linked_columns,
            literals_found=sorted(all_literals),
            variant_contributions=variant_contributions,
            schema_text=pruned_text,
            few_shot_example=few_shot_ref,
        )

    def _revise_literals(
        self,
        extracted: ExtractedFields,
        question: str,
        evidence: str,
        schema_text: str,
        variant_name: str,
    ) -> ExtractedFields:
        """Revise trial SQL when literals don't match any column values via LSH.

        Implements paper Algorithm 2.d-2.e: re-prompt the LLM with an augmented
        schema showing which columns contain values similar to unmatched literals.
        """
        _, unmatched, literal_to_cols = self._literal_matcher.match_detailed(
            extracted.literals
        )
        if not unmatched:
            return extracted

        # Build candidates: for unmatched literals, query LSH individually to find
        # columns with *similar* (not exact) values that might help the LLM
        literal_candidates: dict[str, list[str]] = {}
        for lit in unmatched:
            literal_candidates[lit] = literal_to_cols.get(lit, [])

        logger.info(
            "Variant '%s': %d/%d literals unmatched, revising trial SQL",
            variant_name, len(unmatched), len(extracted.literals),
        )

        revised = self._trial_gen.revise_and_extract(
            question=question,
            evidence=evidence,
            schema_text=schema_text,
            previous_sql=extracted.sql,
            literal_candidates=literal_candidates,
            variant_name=variant_name,
        )

        if not revised.tables:
            logger.warning("Variant '%s': revision produced empty result, keeping original", variant_name)
            return extracted

        # Union original + revised for high recall
        merged = ExtractedFields(
            tables=extracted.tables | revised.tables,
            columns=extracted.columns | revised.columns,
            literals=extracted.literals | revised.literals,
            sql=revised.sql,
        )
        logger.info(
            "Variant '%s': revision added %d tables, %d columns",
            variant_name,
            len(revised.tables - extracted.tables),
            len(revised.columns - extracted.columns),
        )
        return merged

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _generate_variants(
        self,
        question: str,
        evidence: str,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
    ) -> dict[str, str]:
        return {
            "full_schema": self._formatter.full_schema(schema),
            "minimal_profile": self._formatter.minimal_profile(schema, profile),
            "maximal_profile": self._formatter.maximal_profile(schema, profile),
            "focused_schema": self._formatter.focused_schema(
                schema, profile, self._lsh, question, evidence,
                vector_index=self._vector_index, llm=self._llm,
            ),
            "full_profile": self._formatter.full_profile(schema, profile),
        }

    def _union_fields(
        self,
        all_extracted: list[tuple[str, ExtractedFields]],
        schema: DatabaseSchema,
    ) -> tuple[set[str], set[tuple[str, str]], set[str]]:
        """Union tables, columns, and literals across all variants.

        Delegates to linking_utils.union_fields (shared with SinglePromptLinker).
        """
        plain_list = [extracted for _name, extracted in all_extracted]
        return _union_fields_util(plain_list, schema)

    def _add_join_paths(
        self,
        tables: set[str],
        columns: set[tuple[str, str]],
        schema: DatabaseSchema,
    ) -> tuple[set[str], set[tuple[str, str]]]:
        """Delegates to linking_utils.add_join_paths."""
        return _add_join_paths_util(
            tables, columns, schema,
            use_bridge=self._use_bridge_join,
            join_graph=self._join_graph,
        )

    def _render_pruned_schema(
        self,
        tables: set[str],
        columns: set[tuple[str, str]],
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        bird_meta: "BirdMetadata | None" = None,
        join_graph: "JoinGraph | None" = None,
    ) -> str:
        """Delegates to linking_utils.render_pruned_schema."""
        return _render_pruned_schema_util(
            tables, columns, schema, profile, bird_meta, join_graph,
            use_quirks=self._use_quirks,
        )

    def _fallback_full_schema(
        self,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        bird_meta: "BirdMetadata | None" = None,
        join_graph: "JoinGraph | None" = None,
    ) -> SchemaLinkResult:
        """Delegates to linking_utils.fallback_full_schema."""
        return _fallback_full_schema_util(schema, profile, bird_meta, join_graph)
