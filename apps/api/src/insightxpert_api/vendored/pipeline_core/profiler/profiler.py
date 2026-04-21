import asyncio
import logging
import sys

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.db import open_db
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.llm.gemini import GeminiLLM
from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile
from insightxpert_api.vendored.pipeline_core.profiler.lsh_builder import LSHBuilder
from insightxpert_api.vendored.pipeline_core.profiler.quirk_detector import QuirkEnricher
from insightxpert_api.vendored.pipeline_core.profiler.schema_extractor import SchemaExtractor, get_schema_extractor
from insightxpert_api.vendored.pipeline_core.profiler.stats_collector import StatsCollector
from insightxpert_api.vendored.pipeline_core.profiler.summary_generator import SummaryGenerator
from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorBuilder

logger = logging.getLogger(__name__)

# Subdirectory under profiles/{db_id}/ where evidence-backed artifacts are stored
EVIDENCE_SUBDIR = "evidence"
# Subdirectory for profiles that have been through the bird-enriched LLM pass.
# Composes with EVIDENCE_SUBDIR: profiles/{db}/bird_enriched/ or
# profiles/{db}/evidence/bird_enriched/.
BIRD_ENRICHED_SUBDIR = "bird_enriched"


def _profile_dir(
    db_id: str,
    evidence_backed: bool = False,
    bird_enriched: bool = False,
    profiles_base_dir: "Path | None" = None,  # noqa: F821
) -> "Path":  # noqa: F821
    from pathlib import Path  # local to avoid top-level Path import noise
    base = (profiles_base_dir or settings.profiles_dir) / db_id
    if evidence_backed:
        base = base / EVIDENCE_SUBDIR
    if bird_enriched:
        base = base / BIRD_ENRICHED_SUBDIR
    return base


class Profiler:
    """Orchestrates the full offline profiling pipeline for a single database."""

    def __init__(
        self,
        llm: GeminiLLM,
        quirk_llm: BaseLLM | None = None,
        containment_threshold: float = 0.9,
    ):
        """
        Args:
            llm: primary LLM used for summaries and embeddings.
            quirk_llm: optional separate LLM for quirk enrichment. Use a stronger
                model (e.g. gemini-3.1-pro-preview) here for better semantic hints
                on cryptic columns. Falls back to `llm` if None.
            containment_threshold: min child-side value containment ratio for an
                implicit FK to be accepted as value_verified in join_graph.json
                (default 0.9).
        """
        self._llm = llm
        self._quirk_llm = quirk_llm or llm
        self._containment_threshold = containment_threshold

    async def profile_database(
        self,
        db_id: str,
        with_evidence: bool = False,
        benchmark: str = "bird_dev",
        enrich_quirks: bool = True,
    ) -> DatabaseProfile:
        """Run all five profiling steps and save artifacts.

        benchmark controls which DB path is used:
          "bird_dev" → Databases/{db_id}.sqlite
          "mini_dev" → mini_dev/dev_databases/{db_id}/{db_id}.sqlite
        Profiles are stored under profiles/ (bird_dev) or profiles/mini_dev/ (mini_dev).

        with_evidence=False (default): saves to <profiles_base>/{db_id}/
        with_evidence=True: generates evidence-backed LLM summaries using domain hints
            from test cases, then saves profile + vector index to <profiles_base>/{db_id}/evidence/.
            The LSH index is value-based and identical regardless, so it is always written
            to (and read from) the base directory.
        """
        try:
            db = open_db(db_id, benchmark=benchmark)
        except FileNotFoundError as e:
            logger.error("%s", e)
            sys.exit(1)

        profiles_base_dir = settings.get_profiles_dir(benchmark)
        base_dir = profiles_base_dir / db_id
        base_dir.mkdir(parents=True, exist_ok=True)
        out_dir = base_dir / EVIDENCE_SUBDIR if with_evidence else base_dir
        if with_evidence:
            out_dir.mkdir(parents=True, exist_ok=True)
        self._benchmark = benchmark
        self._profiles_base_dir = profiles_base_dir

        with db:
            # Steps 1–2: synchronous, fast
            logger.info("[1/5] Extracting schema for '%s'...", db_id)
            dialect = settings.get_dialect(benchmark)
            schema = get_schema_extractor(dialect).extract(db)
            # schema.json always lives in the base dir (shared between normal + evidence runs)
            (base_dir / "schema.json").write_text(schema.model_dump_json(indent=2))

            # Join graph: declared FKs + value-verified implicit edges (structural, shared)
            from insightxpert_api.vendored.pipeline_core.profiler.join_graph_builder import build_join_graph
            join_graph = build_join_graph(
                schema, db,
                containment_threshold=self._containment_threshold,
            )
            (base_dir / "join_graph.json").write_text(join_graph.model_dump_json(indent=2))

            logger.info("[2/5] Collecting column statistics...")
            profile = StatsCollector(fast=(dialect == "snowflake")).collect(db, schema)

            # Step 2.5 (evidence run only): build unified evidence before generating summaries
            unified_evidence = ""
            if with_evidence:
                unified_evidence = self._build_unified_evidence(db_id, schema, profile)

            num_cols = sum(len(t.columns) for t in profile.tables)
            total_steps = 6 if enrich_quirks else 5
            _SUMMARY_COL_LIMIT = 1000
            if dialect == "snowflake" and num_cols > _SUMMARY_COL_LIMIT:
                logger.info(
                    "[3/%d] Skipping LLM summaries — %d columns exceeds limit %d (stats + quirks suffice on wide Snowflake DBs)",
                    total_steps, num_cols, _SUMMARY_COL_LIMIT,
                )
            else:
                logger.info(
                    "[3/%d] Generating LLM summaries (%d columns, short+long concurrently)%s...",
                    total_steps, num_cols,
                    " [evidence-backed]" if unified_evidence else "",
                )
                profile = await SummaryGenerator(self._llm).async_generate(
                    schema, profile, unified_evidence=unified_evidence
                )

            # Step 3.5: Quirk enrichment (rule-based + LLM for cryptic columns).
            # Uses BIRD database_description/*.csv as ground truth when available.
            if enrich_quirks:
                logger.info(
                    "[4/%d] Enriching profile quirks (cryptic columns, enums, type mismatches)...",
                    total_steps,
                )
                bird_meta = self._load_bird_metadata(db_id, benchmark)
                enricher = QuirkEnricher(self._quirk_llm, concurrency=10)
                profile, call_count = await enricher.async_enrich(
                    profile, schema, bird_meta=bird_meta
                )
                logger.info(
                    "Quirk enrichment: %d LLM calls (model=%s)",
                    call_count,
                    getattr(self._quirk_llm, "_model", "unknown"),
                )

            (out_dir / "profile.json").write_text(profile.model_dump_json(indent=2))

            # LSH is value-based — identical for normal and evidence runs, always in base dir
            lsh_step = 5 if enrich_quirks else 4
            lsh_path = base_dir / "lsh_index.pkl"
            if dialect == "snowflake":
                logger.info(
                    "[%d/%d] Skipping LSH index build (dialect=snowflake; per-column DISTINCT scans too slow on shared warehouse)",
                    lsh_step, total_steps,
                )
                from datasketch import MinHashLSH
                from insightxpert_api.vendored.pipeline_core.profiler.lsh_builder import LSHIndex, _NUM_PERM, _THRESHOLD
                LSHIndex(lsh=MinHashLSH(threshold=_THRESHOLD, num_perm=_NUM_PERM), value_to_columns={}).save(lsh_path)
            elif not lsh_path.exists() or not with_evidence:
                logger.info("[%d/%d] Building LSH index...", lsh_step, total_steps)
                loop = asyncio.get_running_loop()
                lsh_index = await loop.run_in_executor(None, LSHBuilder().build, db, schema)
                lsh_index.save(lsh_path)
            else:
                logger.info(
                    "[%d/%d] LSH index already exists in base dir — skipping rebuild.",
                    lsh_step, total_steps,
                )

            vec_step = 6 if enrich_quirks else 5
            if dialect == "snowflake" and num_cols > _SUMMARY_COL_LIMIT:
                logger.info(
                    "[%d/%d] Skipping vector index — %d columns > %d; semantic search over that many columns is noise",
                    vec_step, total_steps, num_cols, _SUMMARY_COL_LIMIT,
                )
                import numpy as np
                from insightxpert_api.vendored.pipeline_core.profiler.vector_builder import VectorIndex
                VectorIndex(embeddings=np.zeros((0, 1), dtype=np.float32), column_ids=[]).save(
                    out_dir / "vector_index.npz", out_dir / "vector_columns.json"
                )
            else:
                logger.info("[%d/%d] Building vector index (all embeddings concurrently)...",
                            vec_step, total_steps)
                vector_index = await VectorBuilder().async_build(profile, self._llm)
                vector_index.save(out_dir / "vector_index.npz", out_dir / "vector_columns.json")

        logger.info("Done. Profile saved to %s/", out_dir)
        return profile

    def _load_bird_metadata(self, db_id: str, benchmark: str):
        """Load BIRD database_description/*.csv if available for this benchmark+db.

        Returns None if the description dir doesn't exist (e.g. non-BIRD datasets).
        """
        from pathlib import Path
        from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

        # mini_dev CSVs live under Test/mini_dev/minidev/MINIDEV/dev_databases/{db}/database_description/
        # bird_dev CSVs live under Test/bird_dev/dev/dev_databases/{db}/database_description/
        if benchmark == "mini_dev":
            base = Path("Test/mini_dev/minidev/MINIDEV")
        elif benchmark == "bird_dev":
            base = Path("Test/bird_dev/dev")
        else:
            logger.info("No BIRD metadata for benchmark '%s'", benchmark)
            return None

        if not (base / "dev_databases" / db_id / "database_description").exists():
            logger.info("No database_description dir for '%s' (benchmark=%s)", db_id, benchmark)
            return None

        bird_meta = BirdMetadata(db_id, base)
        if bird_meta:
            logger.info(
                "Loaded BIRD schema docs: %d columns documented for '%s'",
                len(bird_meta._descriptions), db_id,
            )
        return bird_meta if bird_meta else None

    def _build_unified_evidence(self, db_id: str, schema, profile) -> str:
        """Load test-case evidences and consolidate them via LLM. Returns empty string on failure."""
        from insightxpert_api.vendored.pipeline_core.evaluation.loader import load_test_cases
        from insightxpert_api.vendored.pipeline_core.profiler.evidence_unifier import EvidenceUnifier, load_unified_evidence

        benchmark = getattr(self, "_benchmark", "bird_dev")

        # Reuse already-generated unified evidence if it exists
        existing = load_unified_evidence(db_id, profiles_base_dir=getattr(self, "_profiles_base_dir", None))
        if existing:
            logger.info("Reusing existing unified evidence for '%s'.", db_id)
            return existing

        cases = load_test_cases(
            test_file=settings.get_test_file(benchmark),
            db_id=db_id,
            db_dir=settings.get_db_dir(benchmark),
            benchmark=benchmark,
        )
        if not cases:
            logger.warning("No test cases found for '%s' — profiling without evidence.", db_id)
            return ""

        evidences = [c.evidence for c in cases]
        logger.info(
            "Generating unified evidence from %d test cases for '%s'...", len(cases), db_id
        )
        return EvidenceUnifier(self._llm).generate(db_id, evidences, schema, profile)

    @staticmethod
    def load_profile(
        db_id: str,
        evidence_backed: bool = False,
        bird_enriched: bool = False,
        benchmark: str = "bird_dev",
    ) -> DatabaseProfile:
        """Load a previously saved DatabaseProfile from disk; exits if not found.

        evidence_backed=True loads from <profiles_base>/{db_id}/evidence/profile.json.
        bird_enriched=True adds a bird_enriched/ subdir (composes with evidence).
        Falls back gracefully: bird_enriched → strip bird_enriched, then strip evidence.
        """
        profiles_base_dir = settings.get_profiles_dir(benchmark)
        path = _profile_dir(
            db_id, evidence_backed, bird_enriched, profiles_base_dir,
        ) / "profile.json"
        if not path.exists() and bird_enriched:
            logger.warning(
                "Bird-enriched profile not found at %s. "
                "Run: python scripts/build_bird_enriched_profiles.py --db %s. "
                "Falling back to non-enriched profile.",
                path, db_id,
            )
            path = _profile_dir(
                db_id, evidence_backed, False, profiles_base_dir,
            ) / "profile.json"
        if not path.exists() and evidence_backed:
            logger.warning(
                "Evidence-backed profile not found at %s. "
                "Run: python -m insightxpert profile --db %s --with-evidence. "
                "Falling back to base profile.",
                path, db_id,
            )
            path = _profile_dir(
                db_id, False, False, profiles_base_dir,
            ) / "profile.json"
        if not path.exists():
            logger.error(
                "No profile found at %s. Run 'profile --db %s' first.", path, db_id
            )
            sys.exit(1)
        return DatabaseProfile.model_validate_json(path.read_text())

    @staticmethod
    def load_join_graph(
        db_id: str,
        benchmark: str = "bird_dev",
    ) -> "JoinGraph | None":
        """Load a precomputed join graph from disk; returns None if not found.

        join_graph.json lives in the base profile dir (structural, shared
        between normal and evidence-backed profiles).

        Raises:
            ValueError — if the file exists but is in the old format (pre-kind/containment).
        """
        from pydantic import ValidationError
        from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinGraph

        profiles_base_dir = settings.get_profiles_dir(benchmark)
        path = profiles_base_dir / db_id / "join_graph.json"
        if not path.exists():
            logger.debug("No join_graph.json for '%s' — will build at runtime", db_id)
            return None
        raw = path.read_text()
        try:
            return JoinGraph.model_validate_json(raw)
        except ValidationError as exc:
            if '"source"' in raw or "'source'" in raw:
                raise ValueError(
                    f"join_graph.json for '{db_id}' uses the old schema (pre-kind/containment). "
                    f"Rebuild with: python -m insightxpert build-join-graph --db {db_id} --benchmark {benchmark}"
                ) from exc
            raise
