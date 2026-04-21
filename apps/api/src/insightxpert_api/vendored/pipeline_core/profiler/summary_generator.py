import asyncio
import logging

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
from insightxpert_api.vendored.pipeline_core.models.profile import ColumnProfile, DatabaseProfile
from insightxpert_api.vendored.pipeline_core.models.schema import DatabaseSchema

logger = logging.getLogger(__name__)

# Max concurrent LLM calls — stays well within Gemini rate limits
_CONCURRENCY = 20


class SummaryGenerator:
    """Generates mechanical descriptions and LLM short/long summaries for every column."""

    def __init__(self, llm: BaseLLM, concurrency: int = _CONCURRENCY):
        self._llm = llm
        # Semaphore caps concurrent LLM calls to stay within Gemini rate limits
        self._sem = asyncio.Semaphore(concurrency)
        self._jinja = settings.get_jinja_env()
        self._mech_tmpl = self._jinja.get_template("mechanical_profile.j2")
        self._short_tmpl = self._jinja.get_template("short_summary.j2")
        self._long_tmpl = self._jinja.get_template("long_summary.j2")

    async def async_generate(
        self,
        schema: DatabaseSchema,
        profile: DatabaseProfile,
        unified_evidence: str = "",
    ) -> DatabaseProfile:
        """Enrich all columns with LLM summaries concurrently.

        Individual column failures are isolated — a failed column keeps its existing
        (empty) summaries and does not affect other columns.

        unified_evidence: optional consolidated domain hints that are injected into
        each column's short/long summary prompts for semantically richer descriptions.
        """
        schema_tables = {t.name: t for t in schema.tables}

        # Build all tasks upfront: (table_idx, col_idx, coroutine)
        tasks = []
        for t_idx, table_profile in enumerate(profile.tables):
            table_schema = schema_tables[table_profile.name]
            column_names = [c.name for c in table_schema.columns]
            for c_idx, col_profile in enumerate(table_profile.columns):
                tasks.append((t_idx, c_idx, self._enrich_column(col_profile, table_profile.name, column_names, unified_evidence)))

        total = len(tasks)
        logger.debug("Enriching %d columns (concurrency cap=%d)", total, self._sem._value)

        # return_exceptions=True: one column failure does not cancel the others
        results = await asyncio.gather(
            *[coro for _, _, coro in tasks],
            return_exceptions=True,
        )

        failed = 0
        for (t_idx, c_idx, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                col_name = profile.tables[t_idx].columns[c_idx].name
                table_name = profile.tables[t_idx].name
                logger.warning(
                    "Column '%s.%s' enrichment failed after all retries — summaries left empty: %s",
                    table_name, col_name, result,
                )
                failed += 1
            else:
                profile.tables[t_idx].columns[c_idx] = result

        if failed:
            logger.warning("%d/%d columns could not be enriched", failed, total)
        logger.debug("All %d columns processed (%d enriched, %d failed)", total, total - failed, failed)

        return profile

    async def _enrich_column(
        self,
        col: ColumnProfile,
        table_name: str,
        column_names: list[str],
        unified_evidence: str = "",
    ) -> ColumnProfile:
        """Render mechanical description, then fire short and long LLM summaries concurrently.

        If one of short/long fails (all retries exhausted), the other is still used and
        the failed one is left as an empty string.
        """
        # Mechanical description is pure template rendering — no LLM, no semaphore needed
        mech = self._mech_tmpl.render(
            column_name=col.name,
            column_type=col.type,
            table_name=table_name,
            stats=col.stats,
        ).strip()

        short_prompt = self._short_tmpl.render(
            table_name=table_name,
            column_names=column_names,
            column_name=col.name,
            mechanical_description=mech,
            unified_evidence=unified_evidence,
        )
        long_prompt = self._long_tmpl.render(
            table_name=table_name,
            column_names=column_names,
            column_name=col.name,
            mechanical_description=mech,
            unified_evidence=unified_evidence,
        )

        # Fire short + long concurrently, both sharing the semaphore
        async def _call(prompt: str) -> str:
            async with self._sem:
                return (await self._llm.async_generate(prompt)).strip()

        logger.debug("  enriching '%s.%s'", table_name, col.name)

        # return_exceptions=True: a failed short doesn't cancel long (and vice versa)
        short_result, long_result = await asyncio.gather(
            _call(short_prompt), _call(long_prompt),
            return_exceptions=True,
        )

        short: str = ""
        long: str = ""

        if isinstance(short_result, Exception):
            logger.warning("Short summary failed for '%s.%s': %s", table_name, col.name, short_result)
        else:
            short = short_result

        if isinstance(long_result, Exception):
            logger.warning("Long summary failed for '%s.%s': %s", table_name, col.name, long_result)
        else:
            long = long_result

        return col.model_copy(update={
            "mechanical_description": mech,
            "short_summary": short,
            "long_summary": long,
        })
