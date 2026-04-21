"""Single-prompt schema linking: one LLM call for 5 diverse candidate SQL queries."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
from insightxpert_api.vendored.pipeline_core.linker.linking_utils import (
    add_join_paths,
    enrich_question_token_match,
    fallback_full_schema,
    render_pruned_schema,
    union_fields,
)
from insightxpert_api.vendored.pipeline_core.linker.few_shot_retriever import FewShotRetriever
from insightxpert_api.vendored.pipeline_core.linker.literal_matcher import LiteralMatcher
from insightxpert_api.vendored.pipeline_core.linker.trial_query import TrialQueryGenerator
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile
from insightxpert_api.vendored.pipeline_core.models.query import FewShotExampleRef, LinkedField, SchemaLinkResult
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
from insightxpert_api.vendored.pipeline_core.profiler.lsh_builder import LSHIndex
from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorIndex

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinGraph
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)
_INTERP_RE = re.compile(r"<interpretation>(.*?)</interpretation>", re.IGNORECASE | re.DOTALL)
_REPHRASE_RE = re.compile(r"<rephrase[^>]*>(.*?)</rephrase>", re.IGNORECASE | re.DOTALL)

# Forward linking response parsing patterns
_FWD_TABLE_RE = re.compile(r'Table:\s*"([^"]+)"', re.IGNORECASE)
_FWD_COLUMN_RE = re.compile(r'-\s*"([^"]+)"')


class SinglePromptLinker:
    """Schema linking via a single LLM call that generates 5 diverse candidate SQL queries.

    Uses the same post-processing pipeline as SchemaLinker (field extraction,
    LSH literal matching, join path enrichment, pruned schema rendering) but
    replaces the 5 separate variant calls with one prompt.
    """

    def __init__(
        self,
        llm: BaseLLM,
        lsh_index: LSHIndex,
        vector_index: VectorIndex | None = None,
        use_literal_revision: bool = False,
        use_v2_prompt: bool = False,
        use_clean_prompt: bool = False,
        use_semantic: bool = True,
        semantic_on_rephrasings: bool = False,
        use_pruning: bool = False,
        use_forward_linking: bool = False,
        use_bridge_join: bool = False,
        join_graph: "JoinGraph | None" = None,
        use_quirks: bool = True,
        dialect: str = "sqlite",
        few_shot_retriever: FewShotRetriever | None = None,
    ) -> None:
        self._llm = llm
        self._lsh = lsh_index
        self._vector_index = vector_index
        self._use_literal_revision = use_literal_revision
        self._use_v2_prompt = use_v2_prompt
        self._use_semantic = use_semantic
        self._semantic_on_rephrasings = semantic_on_rephrasings
        self._use_pruning = use_pruning
        self._use_forward_linking = use_forward_linking
        self._use_bridge_join = use_bridge_join
        self._join_graph = join_graph
        self._use_quirks = use_quirks
        self._literal_matcher = LiteralMatcher(lsh_index)
        self._dialect = dialect
        self._few_shot_retriever = few_shot_retriever
        if dialect == "snowflake":
            template_name = "single_prompt_linking_snowflake.j2"
        elif use_clean_prompt:
            template_name = "single_prompt_linking_clean.j2"
        elif use_v2_prompt:
            template_name = "single_prompt_linking_v2.j2"
        else:
            template_name = "single_prompt_linking.j2"
        self._template = settings.get_jinja_env().get_template(template_name)
        if use_pruning:
            self._pruning_template = settings.get_jinja_env().get_template("schema_pruning.j2")
        if use_forward_linking:
            self._forward_template = settings.get_jinja_env().get_template("forward_linking.j2")

    # ------------------------------------------------------------------
    # Enrichment helpers (each returns a set of (table, column) pairs)
    # ------------------------------------------------------------------

    def _enrich_semantic(self, question: str, evidence: str) -> set[tuple[str, str]]:
        """Embed question and search vector index for similar columns."""
        if self._vector_index is None:
            return set()
        query_text = question if not evidence else f"{question} {evidence}"
        try:
            query_embedding = self._llm.embed([query_text])[0]
            if not query_embedding:  # embed returns [] on failure
                return set()
            cols: set[tuple[str, str]] = set()
            for col_id, score in self._vector_index.search(query_embedding, top_k=10):
                if score > 0.5:
                    parts = col_id.split(".", 1)
                    if len(parts) == 2:
                        cols.add((parts[0], parts[1]))
            logger.debug("Semantic matching: %d columns above threshold", len(cols))
            return cols
        except Exception as exc:
            logger.warning("Semantic matching failed, continuing without: %s", exc)
            return set()

    def _enrich_literal_lsh(self, all_literals: set[str]) -> set[tuple[str, str]]:
        """LSH matching on literals extracted from trial SQL queries."""
        return self._literal_matcher.match(all_literals)

    def _prune_columns(
        self,
        question: str,
        evidence: str,
        tables: set[str],
        columns: set[tuple[str, str]],
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        bird_meta: "BirdMetadata | None",
    ) -> tuple[set[str], set[tuple[str, str]]]:
        """Call LLM to prune linked columns down to only what's needed."""
        linked_schema_text = render_pruned_schema(
            tables, columns, schema, profile, bird_meta, self._join_graph,
            use_quirks=self._use_quirks,
        )
        prompt = self._pruning_template.render(
            question=question, evidence=evidence, linked_schema=linked_schema_text,
        )
        logger.info("Schema pruning: calling LLM to prune %d columns", len(columns))
        try:
            raw_response = self._llm.generate(prompt)
        except Exception as exc:
            logger.warning("Schema pruning LLM call failed, keeping unpruned: %s", exc)
            return tables, columns

        pruned: set[tuple[str, str]] = set()
        for line in raw_response.strip().splitlines():
            line = line.strip().strip("-•* ")
            if not line or line.startswith("#") or line.startswith("```"):
                continue
            line = line.replace('"', '').replace("'", "").replace("`", "")
            parts = line.split(".", 1)
            if len(parts) == 2:
                tbl, col = parts[0].strip(), parts[1].strip()
                if tbl and col:
                    pruned.add((tbl, col))

        if not pruned:
            logger.warning("Schema pruning returned no valid columns, keeping unpruned set")
            return tables, columns

        original_lookup: dict[tuple[str, str], tuple[str, str]] = {
            (t.lower(), c.lower()): (t, c) for t, c in columns
        }
        validated: set[tuple[str, str]] = set()
        for tbl, col in pruned:
            key = (tbl.lower(), col.lower())
            if key in original_lookup:
                validated.add(original_lookup[key])

        if not validated:
            logger.warning("Schema pruning: no valid columns after validation, keeping unpruned")
            return tables, columns

        pruned_tables = {t for t, _ in validated}
        logger.info(
            "Schema pruning: %d → %d columns (%d pruned)",
            len(columns), len(validated), len(columns) - len(validated),
        )
        return pruned_tables, validated

    def _forward_link(
        self,
        question: str,
        evidence: str,
        schema_text: str,
        schema: DatabaseSchema,
    ) -> set[tuple[str, str]]:
        """LLM directly identifies relevant tables/columns from full schema."""
        prompt = self._forward_template.render(
            question=question, evidence=evidence, schema_text=schema_text,
        )
        logger.info("Forward linking: calling LLM to identify relevant columns")
        try:
            raw_response = self._llm.generate(prompt)
        except Exception as exc:
            logger.warning("Forward linking LLM call failed: %s", exc)
            return set()

        # Parse Table: "name" / - "column" format
        import re
        forward_cols: set[tuple[str, str]] = set()
        current_table = None

        # Also handle table.column format
        for line in raw_response.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("```"):
                continue
            # Table: "name" or Table: name
            tm = re.match(r'(?:Table:\s*)?["\']?(\w+)["\']?\s*$', line)
            if tm and not "." in line:
                current_table = tm.group(1)
                continue
            # - "column" or - column
            cm = re.match(r'\s*[-•*]\s*["\']?([^"\'(]+?)["\']?\s*(?:\(|$)', line)
            if cm and current_table:
                forward_cols.add((current_table, cm.group(1).strip()))
                continue
            # table.column format
            line_clean = line.replace('"', '').replace("'", "").replace("`", "").strip("-•* ")
            parts = line_clean.split(".", 1)
            if len(parts) == 2:
                tbl, col = parts[0].strip(), parts[1].strip()
                if tbl and col:
                    forward_cols.add((tbl, col))

        if not forward_cols:
            logger.warning("Forward linking: no columns parsed from response")
            return set()

        # Validate against schema (case-insensitive)
        schema_lookup: dict[tuple[str, str], tuple[str, str]] = {}
        for t in schema.tables:
            for c in t.columns:
                schema_lookup[(t.name.lower(), c.name.lower())] = (t.name, c.name)

        validated: set[tuple[str, str]] = set()
        for tbl, col in forward_cols:
            key = (tbl.lower(), col.lower())
            if key in schema_lookup:
                validated.add(schema_lookup[key])

        logger.info("Forward linking: %d columns identified (%d validated)", len(forward_cols), len(validated))
        return validated

    def _enrich_few_shot(
        self, db_id: str, question: str, schema: DatabaseSchema,
    ) -> tuple[set[tuple[str, str]], FewShotExampleRef | None]:
        """Retrieve top-1 few-shot example for db_id and resolve its columns to canonical schema names.

        Returns ``(canonical_columns, example_ref)``. Empty set + None if retrieval is disabled or fails.
        """
        if self._few_shot_retriever is None:
            return set(), None
        example = self._few_shot_retriever.retrieve(db_id, question)
        if example is None:
            return set(), None

        # Build (table_lower, col_lower) -> (canon_table, canon_col) lookup.
        canon: dict[tuple[str, str], tuple[str, str]] = {}
        for t in schema.tables:
            for c in t.columns:
                canon[(t.name.lower(), c.name.lower())] = (t.name, c.name)

        resolved: set[tuple[str, str]] = set()
        dropped = 0
        for tbl, col in example.columns:
            if not tbl:
                continue
            key = (tbl.lower(), col.lower())
            mapped = canon.get(key)
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
        benchmark: str = "bird_dev",
    ) -> SchemaLinkResult:
        """Generate 5 candidate SQL queries in one LLM call and build a focused schema.

        Steps:
        1. Format full schema with profiling descriptions
        2. Single LLM call to generate 5 diverse candidate SQL queries
        3. Parse SQL queries from fenced code blocks
        4. Extract fields (tables, columns, literals) from each query
        5. Union all fields, run LSH literal matching, add join paths
        6. Render pruned schema and return SchemaLinkResult
        """
        # 1. Format full schema
        schema_text = SchemaFormatter(join_graph=self._join_graph).format(
            schema, profile, metadata_mode="profiling", bird_meta=bird_meta,
        )

        # 1b. Optional forward linking (RSL-SQL style)
        forward_cols: set[tuple[str, str]] = set()
        if self._use_forward_linking:
            forward_cols = self._forward_link(question, evidence, schema_text, schema)

        # 2. Render prompt and call LLM
        prompt = self._template.render(
            question=question,
            evidence=evidence,
            schema_text=schema_text,
        )
        logger.info("Single-prompt linking: generating 5 candidate SQL queries")
        logger.debug("Single-prompt linking prompt:\n%s", prompt)
        raw_response = self._llm.generate(prompt)
        logger.debug("Single-prompt linking raw response:\n%s", raw_response)

        # 3. Parse SQL queries and question interpretation from response
        sql_queries = _FENCE_RE.findall(raw_response)
        logger.info("Single-prompt linking: parsed %d SQL queries from response", len(sql_queries))

        interp_match = _INTERP_RE.search(raw_response)
        question_interpretation = interp_match.group(1).strip() if interp_match else ""

        # Extract schema-grounded rephrasings (v2 prompt)
        rephrasings = _REPHRASE_RE.findall(raw_response)
        if rephrasings:
            logger.info("Single-prompt linking: extracted %d rephrasings", len(rephrasings))
            for i, r in enumerate(rephrasings, 1):
                logger.debug("Rephrase %d: %s", i, r.strip())
            question_interpretation = " | ".join(r.strip() for r in rephrasings)
        elif question_interpretation:
            logger.info("Single-prompt linking: extracted question interpretation")
        else:
            logger.debug("Single-prompt linking: no question interpretation found in response")

        if not sql_queries:
            logger.warning("Single-prompt linking: no SQL queries found in response; falling back to full schema")
            return fallback_full_schema(schema, profile, bird_meta, self._join_graph)

        # 4. Extract fields from each query
        all_extracted = []
        for i, sql in enumerate(sql_queries):
            sql = sql.strip().rstrip(";").strip()
            extracted = TrialQueryGenerator._parse_fields(sql)
            extracted.sql = sql
            logger.debug(
                "Single-prompt query %d: %d tables, %d columns, %d literals",
                i + 1, len(extracted.tables), len(extracted.columns), len(extracted.literals),
            )
            all_extracted.append(extracted)

        # 5. Union all fields
        tables, columns, all_literals = union_fields(all_extracted, schema)

        # --- Column source tracking ---
        column_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
        for t, c in columns:
            column_sources[(t, c)].add("trial_sql")

        # Merge forward linking results
        if forward_cols:
            new_from_forward = forward_cols - columns
            for t, c in forward_cols:
                tables.add(t)
                columns.add((t, c))
                column_sources[(t, c)].add("forward")
            logger.info("Forward linking: added %d new columns", len(new_from_forward))

        # Build col->tables lookup for resolving unqualified columns
        col_to_tables: dict[str, list[str]] = {}
        for t in schema.tables:
            for c in t.columns:
                col_to_tables.setdefault(c.name, []).append(t.name)

        # --- Run forward linking if enabled ---
        forward_cols: set[tuple[str, str]] = set()
        if self._use_forward_linking:
            forward_cols = self._forward_link(question, evidence, schema_text, schema)

        # --- Run enrichment steps in parallel (semantic + literal_lsh) ---
        semantic_cols: set[tuple[str, str]] = set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            if self._use_semantic:
                fut_sem = pool.submit(self._enrich_semantic, question, evidence)
            fut_llsh = pool.submit(self._enrich_literal_lsh, all_literals)

            if self._use_semantic:
                semantic_cols = fut_sem.result()
            literal_cols = fut_llsh.result()

        # Semantic on rephrasings: also embed each rephrase and search
        if self._semantic_on_rephrasings and rephrasings and self._vector_index is not None:
            for reph in rephrasings:
                reph_cols = self._enrich_semantic(reph.strip(), evidence)
                semantic_cols |= reph_cols

        # Merge forward linking results and track sources
        new_from_forward = forward_cols - columns
        for t, c in forward_cols:
            tables.add(t)
            columns.add((t, c))
            column_sources[(t, c)].add("forward")
        if forward_cols:
            logger.info(
                "Forward linking: %d columns identified, %d new (not in trial SQL)",
                len(forward_cols), len(new_from_forward),
            )

        # Merge results and track sources
        new_from_semantic = semantic_cols - columns
        for t, c in semantic_cols:
            tables.add(t)
            columns.add((t, c))
            column_sources[(t, c)].add("semantic")

        new_from_literal_lsh = literal_cols - columns
        for table_name, col_name in literal_cols:
            tables.add(table_name)
            columns.add((table_name, col_name))
            column_sources[(table_name, col_name)].add("literal_lsh")

        # Optional literal revision: re-prompt for unmatched literals
        if self._use_literal_revision and all_literals:
            _, unmatched, literal_to_cols = self._literal_matcher.match_detailed(all_literals)
            if unmatched:
                literal_candidates: dict[str, list[str]] = {
                    lit: literal_to_cols.get(lit, []) for lit in unmatched
                }
                logger.info(
                    "Single-prompt linking: %d/%d literals unmatched, revising",
                    len(unmatched), len(all_literals),
                )
                best_sql = all_extracted[0].sql if all_extracted else ""
                trial_gen = TrialQueryGenerator(self._llm)
                revised = trial_gen.revise_and_extract(
                    question=question,
                    evidence=evidence,
                    schema_text=schema_text,
                    previous_sql=best_sql,
                    literal_candidates=literal_candidates,
                    variant_name="single_prompt",
                )
                if revised.tables:
                    tables |= revised.tables
                    all_literals |= revised.literals
                    for table_ref, col_name in revised.columns:
                        if table_ref:
                            columns.add((table_ref, col_name))
                            tables.add(table_ref)
                        else:
                            for tname in col_to_tables.get(col_name, []):
                                columns.add((tname, col_name))
                                tables.add(tname)

        # --- Add PK/FK join-path columns for every linked table ---
        pre_join = set(columns)
        pre_tables = set(tables)
        tables, columns = add_join_paths(
            tables, columns, schema,
            use_bridge=self._use_bridge_join,
            join_graph=self._join_graph,
        )
        for t, c in columns - pre_join:
            source = "join_path_bridge" if self._use_bridge_join else "join_path"
            column_sources[(t, c)].add(source)
        for t in tables - pre_tables:
            # Bridge tables added — tag all their columns as bridge-sourced
            for tc_pair in columns:
                if tc_pair[0] == t and tc_pair not in pre_join:
                    column_sources[tc_pair].add("bridge_table")

        # --- V2 enrichment: question token matching ---
        if self._use_v2_prompt:
            new_qtoken = enrich_question_token_match(
                tables, columns, schema, question, evidence,
            )
            for t, c in new_qtoken:
                column_sources[(t, c)].add("question_token")

        # --- Few-shot retrieval: union the retrieved example's gold-SQL columns ---
        few_shot_cols, few_shot_ref = self._enrich_few_shot(db_id, question, schema)
        new_from_few_shot = few_shot_cols - columns
        for t, c in few_shot_cols:
            tables.add(t)
            columns.add((t, c))
            column_sources[(t, c)].add("few_shot")
        if few_shot_ref is not None:
            logger.info(
                "few-shot merged into linked schema: cols_from_example=%d new=%d",
                len(few_shot_cols), len(new_from_few_shot),
            )

        # --- Optional LLM-based column pruning (CHESS-style) ---
        if self._use_pruning:
            pre_prune = set(columns)
            tables, columns = self._prune_columns(
                question, evidence, tables, columns, schema, profile, bird_meta,
            )
            for t, c in pre_prune - columns:
                column_sources[(t, c)].add("pruned")

        if not columns:
            logger.warning("Single-prompt linking produced zero columns; falling back to full schema")
            return fallback_full_schema(schema, profile, bird_meta, self._join_graph)

        # --- Log column source summary ---
        source_counts: dict[str, int] = defaultdict(int)
        source_new: dict[str, int] = defaultdict(int)
        for sources in column_sources.values():
            for s in sources:
                source_counts[s] += 1
        source_new["forward"] = len(new_from_forward)
        source_new["semantic"] = len(new_from_semantic)
        source_new["literal_lsh"] = len(new_from_literal_lsh)
        if self._use_v2_prompt:
            source_new["question_token"] = len(new_qtoken)
        all_sources = ["trial_sql", "semantic", "literal_lsh", "join_path"]
        if self._use_forward_linking:
            all_sources.append("forward")
        if self._use_v2_prompt:
            all_sources += ["question_token"]
        if few_shot_ref is not None:
            all_sources.append("few_shot")
            source_new["few_shot"] = len(new_from_few_shot)
        parts = []
        for src in all_sources:
            cnt = source_counts.get(src, 0)
            new = source_new.get(src, 0)
            if new:
                parts.append(f"{src}={cnt}(+{new} new)")
            else:
                parts.append(f"{src}={cnt}")
        logger.info(
            "Schema linking sources: %s → total %d columns",
            ", ".join(parts), len(columns),
        )

        # 5b. Optional LLM-based column pruning (CHESS-style re-ranking)
        if self._use_pruning:
            pre_prune_columns = set(columns)
            tables, columns = self._prune_columns(
                question, evidence, tables, columns, schema, profile, bird_meta,
            )
            # Track pruned columns in column_sources
            for t, c in pre_prune_columns - columns:
                column_sources[(t, c)].add("pruned")

        # 6. Render pruned schema
        pruned_text = render_pruned_schema(
            tables, columns, schema, profile, bird_meta, self._join_graph,
            use_quirks=self._use_quirks,
        )

        total_cols = sum(len(t.columns) for t in schema.tables)
        logger.info(
            "Single-prompt linking done: %d/%d tables, %d/%d columns linked",
            len(tables), len(schema.tables),
            len(columns), total_cols,
        )

        # Serialize column_sources for the result model
        serialized_sources: dict[str, list[str]] = {
            f"{t}.{c}": sorted(sources)
            for (t, c), sources in sorted(column_sources.items())
        }

        linked_columns = [
            LinkedField(table=t, column=c) for t, c in sorted(columns)
        ]
        return SchemaLinkResult(
            linked_tables=sorted(tables),
            linked_columns=linked_columns,
            literals_found=sorted(all_literals),
            variant_contributions={"single_prompt": len(columns)},
            schema_text=pruned_text,
            question_interpretation=question_interpretation,
            column_sources=serialized_sources,
            few_shot_example=few_shot_ref,
        )


def _parse_forward_response(
    response: str,
    schema: DatabaseSchema,
) -> set[tuple[str, str]]:
    """Parse the forward linking LLM response into (table, column) pairs.

    Matches parsed names against the schema case-insensitively, returning
    canonical names from the schema. Unrecognized tables/columns are skipped
    with a debug log.
    """
    # Build case-insensitive lookup maps from the schema
    table_lookup: dict[str, str] = {}  # lower → canonical
    col_lookup: dict[str, dict[str, str]] = {}  # lower_table → {lower_col → canonical_col}
    for table in schema.tables:
        table_lookup[table.name.lower()] = table.name
        col_map: dict[str, str] = {}
        for col in table.columns:
            col_map[col.name.lower()] = col.name
        col_lookup[table.name.lower()] = col_map

    result: set[tuple[str, str]] = set()
    current_table: str | None = None
    current_table_lower: str | None = None

    for line in response.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Try to match a table line
        table_match = _FWD_TABLE_RE.search(stripped)
        if table_match:
            raw_table = table_match.group(1)
            lower_table = raw_table.lower()
            if lower_table in table_lookup:
                current_table = table_lookup[lower_table]
                current_table_lower = lower_table
            else:
                logger.debug("Forward linking: unknown table '%s', skipping", raw_table)
                current_table = None
                current_table_lower = None
            continue

        # Try to match a column line
        col_match = _FWD_COLUMN_RE.search(stripped)
        if col_match and current_table is not None and current_table_lower is not None:
            raw_col = col_match.group(1)
            lower_col = raw_col.lower()
            canonical_col = col_lookup.get(current_table_lower, {}).get(lower_col)
            if canonical_col:
                result.add((current_table, canonical_col))
            else:
                logger.debug(
                    "Forward linking: unknown column '%s' in table '%s', skipping",
                    raw_col, current_table,
                )

    logger.info("Forward linking: parsed %d valid (table, column) pairs from response", len(result))
    return result
