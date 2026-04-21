"""End-to-end text-to-SQL pipeline orchestrator."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.db import open_db
from insightxpert_api.vendored.pipeline_core.evaluation.executor import SQLExecutor
from insightxpert_api.vendored.pipeline_core.evaluation.reporter import EvalReporter
from insightxpert_api.vendored.pipeline_core.generator.candidate_generator import CandidateGenerator
from insightxpert_api.vendored.pipeline_core.generator.sql_validator import SQLValidator
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.evaluation import EvalReport, EvalResult
from insightxpert_api.vendored.pipeline_core.models.query import QueryRequest, QueryResponse, QueryResult, RefinedSQL, SchemaLinkResult
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema
from insightxpert_api.vendored.pipeline_core.profiler.lsh_builder import LSHIndex
from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorIndex

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.linker.few_shot_retriever import FewShotRetriever
    from insightxpert_api.vendored.pipeline_core.models.query import FewShotExampleRef
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        llm: BaseLLM,
        *,
        use_linking: bool = True,
        linking_mode: str = "multi-variant",
        use_refinement: bool = True,
        max_refinement_iterations: int = 2,
        evidence_profile: bool = False,
        benchmark: str = "bird_dev",
        metadata_mode: str = "profiling",
        use_literal_revision: bool = False,
        num_candidates: int = 1,
        use_construction_checks: bool = False,
        reuse_linking: dict[int, str] | None = None,
        perfect_linking_data: dict[str, dict] | None = None,
        use_intent_classify: bool = False,
        use_self_correct: bool = False,
        use_dual_schema: bool = False,
        use_bridge_join: bool = False,
        use_forward_linking: bool = False,
        use_pruning: bool = False,
        use_bird_enriched: bool = False,
        use_quirks: bool = True,
        use_few_shot: bool = False,
    ) -> None:
        self._llm = llm
        # Reconcile use_linking (legacy) with linking_mode (new).
        # If linking_mode was explicitly set to something other than the default,
        # it takes precedence.  Otherwise honour the legacy use_linking flag.
        if linking_mode != "multi-variant":
            self._linking_mode = linking_mode
        elif not use_linking:
            self._linking_mode = "none"
        else:
            self._linking_mode = linking_mode
        self._use_refinement = use_refinement
        self._max_refinement_iterations = max_refinement_iterations
        self._evidence_profile = evidence_profile
        self._benchmark = benchmark
        self._dialect = settings.get_dialect(benchmark)
        self._metadata_mode = metadata_mode
        self._use_literal_revision = use_literal_revision
        self._num_candidates = num_candidates
        self._use_construction_checks = use_construction_checks
        self._use_intent_classify = use_intent_classify
        self._use_self_correct = use_self_correct
        self._use_dual_schema = use_dual_schema
        self._use_bridge_join = use_bridge_join
        self._use_forward_linking = use_forward_linking
        self._use_pruning = use_pruning
        self._use_bird_enriched = use_bird_enriched
        self._use_quirks = use_quirks
        self._use_few_shot = use_few_shot
        # Lazy-loaded shared FewShotRetriever — built on first use, then reused
        self._few_shot_retriever: "FewShotRetriever | None" = None
        self._few_shot_loaded = False
        # Cache LSH + vector indices per db_id — loaded once, reused across questions
        self._index_cache: dict[str, tuple[LSHIndex, VectorIndex | None]] = {}
        # Cache BirdMetadata per db_id (only populated for bird/fused metadata modes)
        self._bird_meta_cache: dict[str, BirdMetadata] = {}
        # Cache precomputed join graphs per db_id (only used with --bridge-join)
        self._join_graph_cache: dict[str, object] = {}  # JoinGraph | None
        # Reuse linking: question_id -> schema_text from a previous run
        self._reuse_linking = reuse_linking
        # Perfect linking, keyed by question text, with per-question
        # (schema_text, tables, columns) for runtime few-shot augmentation.
        self._perfect_linking_data = perfect_linking_data or {}
        self._perfect_by_question: dict[str, dict] = {
            entry["question"]: entry
            for entry in self._perfect_linking_data.values()
            if "question" in entry
        }

    def _load_indices(self, db_id: str) -> tuple[LSHIndex, VectorIndex | None]:
        """Load and cache LSH + vector indices for a database."""
        if db_id in self._index_cache:
            return self._index_cache[db_id]

        from insightxpert_api.vendored.pipeline_core.config import settings
        from insightxpert_api.vendored.pipeline_core.profiler.profiler import EVIDENCE_SUBDIR

        base_dir = settings.get_profiles_dir(self._benchmark) / db_id

        lsh_path = base_dir / "lsh_index.pkl"
        if not lsh_path.exists():
            raise FileNotFoundError(
                f"LSH index not found at {lsh_path}. Re-run: python -m insightxpert profile --db {db_id}"
            )

        logger.info("Loading LSH index for '%s'...", db_id)
        lsh_index = LSHIndex.load(lsh_path)

        vec_dir = base_dir / EVIDENCE_SUBDIR if self._evidence_profile else base_dir
        vec_npz = vec_dir / "vector_index.npz"
        vec_cols = vec_dir / "vector_columns.json"
        vector_index: VectorIndex | None = None
        if vec_npz.exists() and vec_cols.exists():
            if self._evidence_profile:
                logger.info("Loading evidence-backed vector index for '%s'...", db_id)
            vector_index = VectorIndex.load(vec_npz, vec_cols)
        elif self._evidence_profile:
            logger.warning(
                "Evidence-backed vector index not found for '%s'. "
                "Run: python -m insightxpert profile --db %s --with-evidence. "
                "Falling back to base vector index.",
                db_id, db_id,
            )
            fallback_npz = base_dir / "vector_index.npz"
            fallback_cols = base_dir / "vector_columns.json"
            if fallback_npz.exists() and fallback_cols.exists():
                vector_index = VectorIndex.load(fallback_npz, fallback_cols)

        self._index_cache[db_id] = (lsh_index, vector_index)
        return lsh_index, vector_index

    def _load_join_graph(self, db_id: str) -> "JoinGraph | None":
        """Load and cache precomputed join graph for bridge-join mode."""
        if db_id not in self._join_graph_cache:
            from insightxpert_api.vendored.pipeline_core.profiler.profiler import Profiler
            self._join_graph_cache[db_id] = Profiler.load_join_graph(
                db_id, benchmark=self._benchmark,
            )
        return self._join_graph_cache[db_id]

    def _augment_perfect_schema(
        self,
        entry: dict,
        question: str,
        db_id: str,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        bird_meta: "BirdMetadata | None",
    ) -> "tuple[str, FewShotExampleRef | None] | None":
        """Re-render the perfect schema with few-shot example columns unioned in.

        Returns ``(schema_text, few_shot_example_ref)``. Returns None if the
        cache entry lacks structured ``tables``/``columns`` (old cache format)
        — caller should fall back to the stored schema_text as-is.
        """
        if "tables" not in entry or "columns" not in entry:
            logger.warning(
                "Perfect-linking cache entry for question %.60s lacks tables/columns; "
                "rebuild the cache to enable few-shot augmentation.",
                question,
            )
            return None

        from insightxpert_api.vendored.pipeline_core.linker.linking_utils import add_join_paths, render_pruned_schema
        from insightxpert_api.vendored.pipeline_core.models.query import FewShotExampleRef

        tables: set[str] = set(entry["tables"])
        columns: set[tuple[str, str]] = {tuple(c) for c in entry["columns"]}

        retriever = self._get_few_shot_retriever()
        ref: "FewShotExampleRef | None" = None
        if retriever is not None:
            example = retriever.retrieve(db_id, question)
            if example is not None:
                canon: dict[tuple[str, str], tuple[str, str]] = {}
                for t in schema.tables:
                    for c in t.columns:
                        canon[(t.name.lower(), c.name.lower())] = (t.name, c.name)
                added: set[tuple[str, str]] = set()
                for tbl, col in example.columns:
                    if not tbl:
                        continue
                    mapped = canon.get((tbl.lower(), col.lower()))
                    if mapped is None:
                        continue
                    added.add(mapped)
                new_cols = added - columns
                new_tables = {t for t, _ in new_cols} - tables
                columns |= added
                tables |= {t for t, _ in added}
                logger.info(
                    "few-shot augmenting perfect schema for db=%s: +%d new cols, +%d new tables (sim=%.3f)",
                    db_id, len(new_cols), len(new_tables), example.similarity,
                )
                ref = FewShotExampleRef(
                    question=example.question,
                    gold_sql=example.gold_sql,
                    similarity=example.similarity,
                )

        join_graph = self._load_join_graph(db_id)
        tables, columns = add_join_paths(
            tables, columns, schema,
            use_bridge=self._use_bridge_join,
            join_graph=join_graph,
        )
        schema_text = render_pruned_schema(
            tables, columns, schema, profile, bird_meta, join_graph,
            use_quirks=self._use_quirks,
        )
        return schema_text, ref

    def _get_few_shot_retriever(self) -> "FewShotRetriever | None":
        """Lazy-load the few-shot index once per Pipeline instance."""
        if not self._use_few_shot:
            return None
        if not self._few_shot_loaded:
            from insightxpert_api.vendored.pipeline_core.linker.few_shot_retriever import FewShotRetriever
            self._few_shot_retriever = FewShotRetriever.load(self._llm, benchmark=self._benchmark)
            self._few_shot_loaded = True
            if self._few_shot_retriever is None:
                logger.warning(
                    "use_few_shot=True but few-shot index not loaded; continuing without few-shot.",
                )
        return self._few_shot_retriever

    def _load_bird_meta(self, db_id: str) -> "BirdMetadata | None":
        """Lazily load and cache BirdMetadata for the given db_id."""
        if self._metadata_mode not in ("bird", "fused"):
            return None
        if db_id not in self._bird_meta_cache:
            from insightxpert_api.vendored.pipeline_core.config import settings
            from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata
            meta = BirdMetadata(db_id, settings.mini_dev_dir)
            self._bird_meta_cache[db_id] = meta
        return self._bird_meta_cache[db_id] or None

    def answer(self, request: QueryRequest) -> QueryResponse:
        """Generate SQL for a natural-language question and execute it.

        Raises FileNotFoundError if the database has not been profiled yet.
        """
        from insightxpert_api.vendored.pipeline_core.config import settings
        from insightxpert_api.vendored.pipeline_core.profiler.profiler import Profiler

        profiles_dir = settings.get_profiles_dir(self._benchmark)
        schema_path = profiles_dir / request.db_id / "schema.json"
        if not schema_path.exists():
            raise FileNotFoundError(
                f"No profile found for '{request.db_id}'. "
                f"Run: python -m insightxpert profile --db {request.db_id}"
            )

        schema = DatabaseSchema.model_validate_json(schema_path.read_text())
        profile = Profiler.load_profile(
            request.db_id,
            evidence_backed=self._evidence_profile,
            bird_enriched=self._use_bird_enriched,
            benchmark=self._benchmark,
        )

        bird_meta = self._load_bird_meta(request.db_id)

        # --- Phase 4: Schema Linking ---
        linked_result: SchemaLinkResult | None = None
        schema_text_override: str | None = None

        # Perfect-linking + few-shot: augment the pre-built perfect schema with
        # the retrieved example's gold-SQL columns, then re-render.
        few_shot_example_override: "FewShotExampleRef | None" = None
        if (
            self._use_few_shot
            and request.question in self._perfect_by_question
        ):
            entry = self._perfect_by_question[request.question]
            augmented = self._augment_perfect_schema(
                entry=entry,
                question=request.question,
                db_id=request.db_id,
                schema=schema,
                profile=profile,
                bird_meta=bird_meta,
            )
            if augmented is not None:
                schema_text_override, few_shot_example_override = augmented
                logger.debug("Using few-shot-augmented perfect schema (skipping linking)")

        # If reuse_linking is set, skip linking and use cached schema text
        if schema_text_override is None and self._reuse_linking and request.question in self._reuse_linking:
            schema_text_override = self._reuse_linking[request.question]
            logger.debug("Reusing linked schema (skipping linking)")

        if schema_text_override is None and self._linking_mode != "none":
            try:
                lsh_index, vector_index = self._load_indices(request.db_id)
                join_graph = self._load_join_graph(request.db_id)

                few_shot_retriever = self._get_few_shot_retriever()
                if self._linking_mode in ("single-prompt", "single-prompt-v2", "single-prompt-clean"):
                    from insightxpert_api.vendored.pipeline_core.linker.single_prompt_linker import SinglePromptLinker
                    linker = SinglePromptLinker(
                        self._llm, lsh_index, vector_index,
                        use_literal_revision=self._use_literal_revision,
                        use_v2_prompt=(self._linking_mode == "single-prompt-v2"),
                        use_clean_prompt=(self._linking_mode == "single-prompt-clean"),
                        use_bridge_join=self._use_bridge_join,
                        join_graph=join_graph,
                        use_forward_linking=self._use_forward_linking,
                        use_pruning=self._use_pruning,
                        use_quirks=self._use_quirks,
                        dialect=self._dialect,
                        few_shot_retriever=few_shot_retriever,
                    )
                else:
                    from insightxpert_api.vendored.pipeline_core.linker.schema_linker import SchemaLinker
                    linker = SchemaLinker(
                        self._llm, lsh_index, vector_index,
                        use_literal_revision=self._use_literal_revision,
                        use_bridge_join=self._use_bridge_join,
                        join_graph=join_graph,
                        use_quirks=self._use_quirks,
                        few_shot_retriever=few_shot_retriever,
                    )

                linked_result = linker.link(
                    question=request.question,
                    evidence=request.evidence,
                    schema=schema,
                    profile=profile,
                    bird_meta=bird_meta,
                    db_id=request.db_id,
                    benchmark=self._benchmark,
                )
                schema_text_override = linked_result.schema_text
                logger.info(
                    "Schema linking (%s): %d/%d tables, %d columns linked",
                    self._linking_mode,
                    len(linked_result.linked_tables),
                    len(schema.tables),
                    len(linked_result.linked_columns),
                )
            except Exception as e:
                logger.error("Schema linking failed, using full schema: %s", e)
                linked_result = None
                schema_text_override = None

        # --- Intent classification (optional) ---
        intents: set[str] | None = None
        if self._use_intent_classify:
            from insightxpert_api.vendored.pipeline_core.classifier.intent_classifier import IntentClassifier
            intents = IntentClassifier().classify(request.question, request.evidence)
            logger.info("Intent classification: %s", intents or "ALL (fallback)")

        # --- Generate, validate, and execute candidates ---
        question_interpretation = linked_result.question_interpretation if linked_result else ""
        few_shot_example = (
            linked_result.few_shot_example if linked_result else None
        ) or few_shot_example_override

        if self._use_self_correct:
            # Self-correcting mode: LLM generates SQL with a run_sql tool
            from insightxpert_api.vendored.pipeline_core.classifier.intent_classifier import ALL_INTENTS
            from insightxpert_api.vendored.pipeline_core.config import settings
            from insightxpert_api.vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
            from insightxpert_api.vendored.pipeline_core.generator.self_corrector import SelfCorrector
            corrector = SelfCorrector(
                llm=self._llm,
                db_id=request.db_id,
                benchmark=self._benchmark,
                max_turns=3,
            )
            # Build the prompt the same way CandidateGenerator would
            effective_intents = intents if intents else ALL_INTENTS
            template = settings.get_jinja_env().get_template("sql_generation.j2")
            prompt = template.render(
                question=request.question,
                evidence=request.evidence,
                schema_text=schema_text_override or SchemaFormatter(join_graph=self._load_join_graph(request.db_id)).format(
                    schema, profile, metadata_mode=self._metadata_mode, bird_meta=bird_meta,
                ),
                question_interpretation=question_interpretation,
                intents=effective_intents,
                few_shot_example=few_shot_example,
            )
            cand = corrector.generate(prompt)
            candidates = [cand]
        else:
            candidates = CandidateGenerator(join_graph=self._load_join_graph(request.db_id)).generate_candidates(
                request, schema, profile, self._llm,
                num_candidates=self._num_candidates,
                schema_text_override=schema_text_override,
                metadata_mode=self._metadata_mode,
                bird_meta=bird_meta,
                question_interpretation=question_interpretation,
                intents=intents,
                dialect=self._dialect,
                few_shot_example=few_shot_example,
            )

        validator = SQLValidator(dialect=self._dialect)
        executor = SQLExecutor()
        results: list[QueryResult] = []
        for cand in candidates:
            valid, reason = validator.validate(cand.sql)
            if not valid:
                results.append(QueryResult(sql=cand.sql, error=f"Validation error: {reason}"))
                continue
            if self._use_construction_checks:
                cand.sql = validator.fix_construction_antipatterns(cand.sql, request.question)
            with open_db(request.db_id, benchmark=self._benchmark) as db:
                results.append(executor.execute(db, cand.sql))

        # --- Majority voting (when multiple candidates) ---
        all_candidates: list[CandidateSQL] | None = None
        all_results: list[QueryResult] | None = None
        vote_method: str | None = None

        if self._num_candidates > 1:
            from insightxpert_api.vendored.pipeline_core.generator.majority_voter import MajorityVoter
            vote = MajorityVoter().vote(candidates, results)
            candidate = candidates[vote.winner_index]
            result = results[vote.winner_index]
            all_candidates = candidates
            all_results = results
            vote_method = vote.vote_method
        else:
            candidate = candidates[0]
            result = results[0]

        # --- Dual-schema fallback: try full schema if linked schema failed ---
        if self._use_dual_schema and schema_text_override and result.error:
            candidate, result = self._dual_schema_select(
                request, schema, profile, bird_meta,
                linked_candidate=candidate, linked_result=result,
                question_interpretation=question_interpretation,
                intents=intents,
                few_shot_example=few_shot_example,
            )

        # --- Phase 5: SQL Self-Refinement (on winning candidate only) ---
        refined: RefinedSQL | None = None
        if self._use_refinement:
            from insightxpert_api.vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
            from insightxpert_api.vendored.pipeline_core.refiner.sql_refiner import SQLRefiner
            effective_schema = schema_text_override or SchemaFormatter(join_graph=self._load_join_graph(request.db_id)).format(
                schema, profile, metadata_mode=self._metadata_mode, bird_meta=bird_meta
            )
            refiner = SQLRefiner(self._llm, max_iterations=self._max_refinement_iterations, benchmark=self._benchmark)
            refined = refiner.refine(request, candidate, result, effective_schema, request.db_id)
            if refined.iterations > 0:
                with open_db(request.db_id, benchmark=self._benchmark) as db:
                    result = SQLExecutor().execute(db, refined.sql)
                logger.info(
                    "Refinement: %d iter(s), %s",
                    refined.iterations,
                    "fixed" if not result.error else f"still failing: {result.error}",
                )

        logger.info("Answer for %r: %s", request.question, "OK" if not result.error else result.error)
        return QueryResponse(
            request=request, candidate=candidate, result=result,
            refined=refined, linked_schema=linked_result,
            all_candidates=all_candidates, all_results=all_results,
            vote_method=vote_method,
        )

    # ------------------------------------------------------------------
    # Dual-schema selection
    # ------------------------------------------------------------------

    def _dual_schema_select(
        self,
        request: QueryRequest,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        bird_meta: BirdMetadata | None,
        linked_candidate: CandidateSQL,
        linked_result: QueryResult,
        question_interpretation: str,
        intents: set[str] | None,
        few_shot_example: "FewShotExampleRef | None" = None,
    ) -> tuple[CandidateSQL, QueryResult]:
        """Generate SQL from full schema as fallback when linked schema SQL failed.

        Only called when linked schema SQL errored. Generates from full schema
        and picks whichever works. If both fail, prefers full schema version.
        """
        from insightxpert_api.vendored.pipeline_core.generator.schema_formatter import SchemaFormatter

        join_graph = self._load_join_graph(request.db_id)
        full_schema_text = SchemaFormatter(join_graph=join_graph).format(
            schema, profile, metadata_mode=self._metadata_mode, bird_meta=bird_meta,
        )

        full_candidates = CandidateGenerator(join_graph=join_graph).generate_candidates(
            request, schema, profile, self._llm,
            num_candidates=1,
            schema_text_override=full_schema_text,
            metadata_mode=self._metadata_mode,
            bird_meta=bird_meta,
            question_interpretation=question_interpretation,
            intents=intents,
            dialect=self._dialect,
            few_shot_example=few_shot_example,
        )
        full_candidate = full_candidates[0]

        validator = SQLValidator(dialect=self._dialect)
        executor = SQLExecutor()
        valid, reason = validator.validate(full_candidate.sql)
        if not valid:
            full_result = QueryResult(sql=full_candidate.sql, error=f"Validation error: {reason}")
        else:
            if self._use_construction_checks:
                full_candidate.sql = validator.fix_construction_antipatterns(
                    full_candidate.sql, request.question,
                )
            with open_db(request.db_id, benchmark=self._benchmark) as db:
                full_result = executor.execute(db, full_candidate.sql)

        if not full_result.error:
            logger.info("Dual-schema: full schema SQL succeeded (linked had failed)")
            return full_candidate, full_result

        logger.info("Dual-schema: both linked and full schema SQL failed, keeping full")
        return full_candidate, full_result

    # ------------------------------------------------------------------
    # Checkpoint helpers (shared by sync and async evaluate)
    # ------------------------------------------------------------------

    @staticmethod
    def _load_checkpoint(checkpoint_path: Path | None) -> tuple[list[EvalResult], set[int]]:
        """Load existing checkpoint results and return (results, done_ids)."""
        existing: list[EvalResult] = []
        done_ids: set[int] = set()
        if checkpoint_path and checkpoint_path.exists():
            for line in checkpoint_path.read_text().splitlines():
                line = line.strip()
                if line:
                    r = EvalResult.model_validate_json(line)
                    existing.append(r)
                    done_ids.add(r.question_id)
            logger.info("Resuming: %d already completed, skipping those question IDs", len(existing))
        return existing, done_ids

    def _build_eval_result(self, case, response: QueryResponse, overall: int, total: int) -> EvalResult:
        """Build an EvalResult from a successful QueryResponse."""
        candidate = response.candidate
        predicted_sql = candidate.sql if candidate else ""
        prompt = candidate.prompt if candidate else ""

        refined_sql: str | None = None
        refinement_iterations: int | None = None
        if response.refined is not None:
            refinement_iterations = response.refined.iterations
            if response.refined.iterations > 0:
                refined_sql = response.refined.sql
                predicted_sql = response.refined.sql

        match = False
        relaxed_match = False
        exec_error = response.result.error if response.result else "No result"

        if predicted_sql and not exec_error:
            try:
                with open_db(case.db_id, benchmark=self._benchmark) as db:
                    executor = SQLExecutor()
                    match = executor.execution_match(db, predicted_sql, case.gold_sql)
                    if not match:
                        relaxed_match = executor.execution_match_relaxed(db, predicted_sql, case.gold_sql)
            except Exception as e:
                logger.warning("[%d/%d] execution_match error for %s: %s", overall, total, case.question_id, e)
                exec_error = str(e)

        # Extract column_sources from schema linking result (if available)
        col_sources = None
        if response.linked_schema and response.linked_schema.column_sources:
            col_sources = response.linked_schema.column_sources

        result = EvalResult(
            question_id=case.question_id,
            db_id=case.db_id,
            question=case.question,
            evidence=case.evidence,
            prompt=prompt,
            gold_sql=case.gold_sql,
            predicted_sql=predicted_sql,
            difficulty=case.difficulty,
            execution_match=match,
            execution_match_relaxed=match or relaxed_match,
            error=exec_error if not match else None,
            refined_sql=refined_sql,
            refinement_iterations=refinement_iterations,
            column_sources=col_sources,
        )

        if match:
            logger.info("[%d/%d] ✓ %s", overall, total, case.question_id)
        else:
            logger.warning("[%d/%d] ✗ %s | %s", overall, total, case.question_id, exec_error or "wrong result")
        return result

    def _finalize_report(self, results: list[EvalResult]) -> EvalReport:
        """Build, log, and return the final EvalReport."""
        reporter = EvalReporter()
        report = reporter.report(results)
        report.total_input_tokens = self._llm.total_input_tokens
        report.total_output_tokens = self._llm.total_output_tokens
        report.estimated_cost_usd = reporter.estimate_cost(
            report.total_input_tokens, report.total_output_tokens,
        )
        reporter.log_report(report)
        return report

    # ------------------------------------------------------------------
    # Synchronous evaluate (unchanged behavior)
    # ------------------------------------------------------------------

    def evaluate(self, cases: list, checkpoint_path: Path | None = None) -> EvalReport:
        """Run execution-match evaluation over a list of TestCase objects."""
        from insightxpert_api.vendored.pipeline_core.models.query import QueryRequest

        existing, done_ids = self._load_checkpoint(checkpoint_path)
        pending = [c for c in cases if c.question_id not in done_ids]
        total = len(cases)
        offset = len(existing)
        results: list[EvalResult] = list(existing)

        ckpt_file = open(checkpoint_path, "a") if checkpoint_path else None  # noqa: SIM115
        try:
            for i, case in enumerate(pending, start=1):
                overall = offset + i
                req = QueryRequest(
                    question=case.question,
                    db_id=case.db_id,
                    evidence=case.evidence,
                )
                try:
                    response = self.answer(req)
                except Exception as e:
                    logger.error("[%d/%d] Error on question %s: %s", overall, total, case.question_id, e)
                    result = EvalResult(
                        question_id=case.question_id,
                        db_id=case.db_id,
                        question=case.question,
                        evidence=case.evidence,
                        gold_sql=case.gold_sql,
                        predicted_sql="",
                        difficulty=case.difficulty,
                        error=str(e),
                    )
                    results.append(result)
                    if ckpt_file:
                        ckpt_file.write(result.model_dump_json() + "\n")
                        ckpt_file.flush()
                    continue

                result = self._build_eval_result(case, response, overall, total)
                results.append(result)
                if ckpt_file:
                    ckpt_file.write(result.model_dump_json() + "\n")
                    ckpt_file.flush()
        finally:
            if ckpt_file:
                ckpt_file.close()

        return self._finalize_report(results)

    # ------------------------------------------------------------------
    # Async parallelized evaluate
    # ------------------------------------------------------------------

    async def _async_load_indices(self, db_id: str) -> tuple[LSHIndex, VectorIndex | None]:
        """Load indices with async lock to prevent duplicate loads."""
        if db_id in self._index_cache:
            return self._index_cache[db_id]
        if not hasattr(self, "_index_lock") or self._index_lock is None:
            self._index_lock = asyncio.Lock()
        async with self._index_lock:
            if db_id in self._index_cache:
                return self._index_cache[db_id]
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._load_indices, db_id)

    async def _async_load_bird_meta(self, db_id: str) -> "BirdMetadata | None":
        """Load bird metadata with async lock to prevent duplicate loads."""
        if self._metadata_mode not in ("bird", "fused"):
            return None
        if db_id in self._bird_meta_cache:
            return self._bird_meta_cache[db_id]
        if not hasattr(self, "_bird_meta_lock") or self._bird_meta_lock is None:
            self._bird_meta_lock = asyncio.Lock()
        async with self._bird_meta_lock:
            if db_id in self._bird_meta_cache:
                return self._bird_meta_cache[db_id]
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._load_bird_meta, db_id)

    async def async_answer(self, request: QueryRequest) -> QueryResponse:
        """Async wrapper — pre-populates caches, then runs answer() in a thread."""
        if self._linking_mode != "none":
            await self._async_load_indices(request.db_id)
        await self._async_load_bird_meta(request.db_id)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.answer, request)

    async def async_evaluate(
        self,
        cases: list,
        checkpoint_path: Path | None = None,
        max_concurrent: int = 5,
    ) -> EvalReport:
        """Run evaluation with bounded concurrency via asyncio."""
        from insightxpert_api.vendored.pipeline_core.models.query import QueryRequest

        existing, done_ids = self._load_checkpoint(checkpoint_path)
        pending = [c for c in cases if c.question_id not in done_ids]
        total = len(cases)
        offset = len(existing)
        results: list[EvalResult] = list(existing)

        sem = asyncio.Semaphore(max_concurrent)
        ckpt_lock = asyncio.Lock()
        results_lock = asyncio.Lock()
        completed = {"count": offset}  # mutable counter for progress logging

        ckpt_file = open(checkpoint_path, "a") if checkpoint_path else None  # noqa: SIM115

        async def _process_one(case) -> None:
            async with sem:
                completed["count"] += 1
                overall = completed["count"]
                req = QueryRequest(
                    question=case.question,
                    db_id=case.db_id,
                    evidence=case.evidence,
                )
                try:
                    response = await self.async_answer(req)
                except Exception as e:
                    logger.error("[%d/%d] Error on question %s: %s", overall, total, case.question_id, e)
                    result = EvalResult(
                        question_id=case.question_id,
                        db_id=case.db_id,
                        question=case.question,
                        evidence=case.evidence,
                        gold_sql=case.gold_sql,
                        predicted_sql="",
                        difficulty=case.difficulty,
                        error=str(e),
                    )
                else:
                    result = self._build_eval_result(case, response, overall, total)

                async with results_lock:
                    results.append(result)
                async with ckpt_lock:
                    if ckpt_file:
                        ckpt_file.write(result.model_dump_json() + "\n")
                        ckpt_file.flush()

        try:
            tasks = [_process_one(case) for case in pending]
            await asyncio.gather(*tasks)
        finally:
            if ckpt_file:
                ckpt_file.close()

        return self._finalize_report(results)
