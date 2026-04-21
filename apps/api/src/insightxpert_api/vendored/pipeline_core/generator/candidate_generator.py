"""Generate a SQL candidate from a natural-language question via a single LLM call."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.classifier.intent_classifier import ALL_INTENTS
from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.generator.schema_formatter import SchemaFormatter
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile
from insightxpert_api.vendored.pipeline_core.models.query import CandidateSQL, FewShotExampleRef, QueryRequest
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.models.join_graph import JoinGraph
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)

# Matches fenced code blocks: ```sql, ```sqlite, ```SQL, etc.
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)


class CandidateGenerator:
    def __init__(self, join_graph: "JoinGraph | None" = None) -> None:
        self._join_graph = join_graph

    def generate(
        self,
        request: QueryRequest,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        llm: BaseLLM,
        schema_text_override: str | None = None,  # Phase 4: pruned schema from SchemaLinker
        metadata_mode: str = "profiling",
        bird_meta: "BirdMetadata | None" = None,
        question_interpretation: str = "",
        intents: set[str] | None = None,
        dialect: str = "sqlite",
        few_shot_example: FewShotExampleRef | None = None,
    ) -> CandidateSQL:
        schema_text = schema_text_override or SchemaFormatter(join_graph=self._join_graph).format(
            schema, profile, metadata_mode=metadata_mode, bird_meta=bird_meta
        )

        effective_intents = intents if intents else ALL_INTENTS
        template_name = "sql_generation_snowflake.j2" if dialect == "snowflake" else "sql_generation.j2"
        template = settings.get_jinja_env().get_template(template_name)
        prompt = template.render(
            question=request.question,
            evidence=request.evidence,
            schema_text=schema_text,
            question_interpretation=question_interpretation,
            intents=effective_intents,
            has_join_hubs="Join edges (verified, pick the one relevant to the question):" in schema_text,
            few_shot_example=few_shot_example,
        )

        logger.debug("Prompt sent to LLM:\n%s", prompt)
        raw = llm.generate(prompt)
        logger.debug("Raw LLM response:\n%s", raw)

        sql = self._extract_sql(raw)
        return CandidateSQL(sql=sql, prompt=prompt)

    # Diversity settings per candidate index: (temperature, schema_seed)
    _DIVERSITY = [
        (None, None),    # candidate 0: default temp, alphabetical schema
        (0.7, 42),       # candidate 1: lower temp, shuffled schema
        (0.9, 137),      # candidate 2: higher temp, shuffled schema
    ]

    def generate_candidates(
        self,
        request: QueryRequest,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        llm: BaseLLM,
        num_candidates: int = 1,
        schema_text_override: str | None = None,
        metadata_mode: str = "profiling",
        bird_meta: "BirdMetadata | None" = None,
        question_interpretation: str = "",
        intents: set[str] | None = None,
        dialect: str = "sqlite",
        few_shot_example: FewShotExampleRef | None = None,
    ) -> list[CandidateSQL]:
        """Generate N candidates with diversity via temperature and schema ordering."""
        if num_candidates == 1:
            return [self.generate(
                request, schema, profile, llm,
                schema_text_override=schema_text_override,
                metadata_mode=metadata_mode, bird_meta=bird_meta,
                question_interpretation=question_interpretation,
                intents=intents,
                dialect=dialect,
                few_shot_example=few_shot_example,
            )]

        effective_intents = intents if intents else ALL_INTENTS
        template_name = "sql_generation_snowflake.j2" if dialect == "snowflake" else "sql_generation.j2"
        template = settings.get_jinja_env().get_template(template_name)
        candidates: list[CandidateSQL] = []

        for i in range(num_candidates):
            temperature, seed = self._DIVERSITY[i % len(self._DIVERSITY)]

            # Schema text: use override if available, else format with optional shuffle
            if schema_text_override:
                schema_text = schema_text_override
            else:
                schema_text = SchemaFormatter(join_graph=self._join_graph).format(
                    schema, profile, metadata_mode=metadata_mode,
                    bird_meta=bird_meta, seed=seed,
                )

            prompt = template.render(
                question=request.question,
                evidence=request.evidence,
                schema_text=schema_text,
                question_interpretation=question_interpretation,
                intents=effective_intents,
                has_join_hubs="Join edges (verified, pick the one relevant to the question):" in schema_text,
                few_shot_example=few_shot_example,
            )

            try:
                kwargs = {"temperature": temperature} if temperature is not None else {}
                raw = llm.generate(prompt, **kwargs)
                sql = self._extract_sql(raw)
                candidates.append(CandidateSQL(sql=sql, prompt=prompt))
                logger.info("Candidate %d/%d generated (temp=%s, seed=%s)", i + 1, num_candidates, temperature, seed)
            except Exception as e:
                logger.warning("Candidate %d/%d failed: %s", i + 1, num_candidates, e)
                candidates.append(CandidateSQL(sql="SELECT 1", prompt=prompt))

        return candidates

    def _extract_sql(self, raw: str) -> str:
        match = _FENCE_RE.search(raw)
        if match:
            sql = match.group(1).strip()
        else:
            logger.warning("No fenced code block found in LLM response; using full response as SQL")
            sql = raw.strip()

        # Strip trailing semicolons
        sql = sql.rstrip(";").strip()

        # If multiple statements, take the first SELECT
        if ";" in sql:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt.upper().startswith("SELECT"):
                    return stmt
        return sql
