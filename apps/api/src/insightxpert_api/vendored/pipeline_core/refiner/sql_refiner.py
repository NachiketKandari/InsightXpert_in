"""SQL self-refinement using execution feedback."""
import logging
import re

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.db import open_db
from insightxpert_api.vendored.pipeline_core.evaluation.executor import SQLExecutor
from insightxpert_api.vendored.pipeline_core.generator.sql_validator import SQLValidator
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.query import CandidateSQL, QueryRequest, QueryResult, RefinedSQL
from insightxpert_api.vendored.pipeline_core.refiner.base import BaseRefiner

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)


class SQLRefiner(BaseRefiner):
    def __init__(self, llm: BaseLLM, *, max_iterations: int = 2, benchmark: str = "bird_dev") -> None:
        self._llm = llm
        self._max_iterations = max_iterations
        self._benchmark = benchmark

    def refine(
        self,
        request: QueryRequest,
        candidate: CandidateSQL,
        result: QueryResult,
        schema_text: str,
        db_id: str,
    ) -> RefinedSQL:
        if not self._needs_refinement(result):
            return RefinedSQL(
                sql=candidate.sql,
                iterations=0,
                original_sql=candidate.sql,
            )

        current_sql = candidate.sql
        original_sql = candidate.sql
        prior_attempts: list[dict] = []
        current_result = result

        template = settings.get_jinja_env().get_template("refine_sql.j2")

        for i in range(1, self._max_iterations + 1):
            feedback = current_result.error or "Unknown error"
            try:
                prompt = template.render(
                    schema_text=schema_text,
                    question=request.question,
                    evidence=request.evidence,
                    previous_sql=current_sql,
                    error=current_result.error,
                    iteration=i,
                    prior_attempts=prior_attempts,
                )
                raw = self._llm.generate(prompt)
                new_sql = self._extract_sql(raw)

                valid, reason = SQLValidator().validate(new_sql)
                if not valid:
                    logger.warning("Refiner iter %d: invalid SQL (%s), continuing", i, reason)
                    prior_attempts.append({"sql": current_sql, "feedback": feedback})
                    continue

                with open_db(db_id, benchmark=self._benchmark) as db:
                    new_result = SQLExecutor().execute(db, new_sql)

            except Exception as e:
                logger.warning("Refiner iter %d: exception — %s", i, e)
                break

            prior_attempts.append({"sql": current_sql, "feedback": feedback})
            current_sql = new_sql
            current_result = new_result

            if not self._needs_refinement(new_result):
                logger.debug("Refiner: fixed after %d iteration(s)", i)
                break

        return RefinedSQL(
            sql=current_sql,
            changes=[a["feedback"] for a in prior_attempts],
            iterations=len(prior_attempts),
            original_sql=original_sql,
            final_error=current_result.error,
        )

    @staticmethod
    def _needs_refinement(result: QueryResult) -> bool:
        return result.error is not None

    @staticmethod
    def _extract_sql(raw: str) -> str:
        match = _FENCE_RE.search(raw)
        if match:
            sql = match.group(1).strip()
        else:
            logger.warning("Refiner: no fenced code block found; using full response as SQL")
            sql = raw.strip()

        sql = sql.rstrip(";").strip()
        if ";" in sql:
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt.upper().startswith("SELECT"):
                    return stmt
        return sql
