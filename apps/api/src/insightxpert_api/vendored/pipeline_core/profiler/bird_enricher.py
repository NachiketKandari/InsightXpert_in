"""LLM-synthesized bird_enriched_summary per column.

Fuses three inputs into a single coherent 2-4 sentence description:
  1. Profiling summary  (short_summary — stats-grounded)
  2. Detected quirks     (semantic_hint, enum_labels, type_mismatch, aliases)
  3. BIRD metadata       (column_description + value_description from CSV)

Where the raw concatenation done by `metadata_mode="fused"` just glues strings
together at render time, this pass asks the LLM to reconcile them — flagging
disagreements (BIRD says X, data suggests Y), and translating enum codes into
plain prose.

Skips columns where BIRD has no description: nothing to synthesize, downstream
rendering falls back to short_summary.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from insightxpert_api.vendored.pipeline_core.config import settings
from insightxpert_api.vendored.pipeline_core.models.profile import ColumnProfile, DatabaseProfile

if TYPE_CHECKING:
    from insightxpert_api.vendored.pipeline_core.llm.base import BaseLLM
    from insightxpert_api.vendored.pipeline_core.profiler.bird_metadata import BirdMetadata

logger = logging.getLogger(__name__)


class BirdEnricher:
    """Concurrent LLM synthesizer for bird_enriched_summary.

    Mirrors QuirkEnricher's shape: async, semaphore-limited, failures isolated
    per column.
    """

    def __init__(self, llm: "BaseLLM", concurrency: int = 10) -> None:
        self._llm = llm
        self._sem = asyncio.Semaphore(concurrency)
        self._tmpl = settings.get_jinja_env().get_template("bird_enriched_summary.j2")

    async def async_enrich(
        self,
        profile: DatabaseProfile,
        bird_meta: "BirdMetadata",
    ) -> tuple[DatabaseProfile, int]:
        """Populate col.bird_enriched_summary for every column with BIRD docs.

        Returns (profile, llm_call_count). Mutates profile in-place; return is
        for ergonomic chaining.
        """
        tasks: list[tuple[str, str, asyncio.Task]] = []
        for table in profile.tables:
            for col in table.columns:
                bird_desc = bird_meta.get(table.name, col.name)
                if not bird_desc:
                    continue
                task = asyncio.create_task(
                    self._enrich_one(table.name, col, bird_desc)
                )
                tasks.append((table.name, col.name, task))

        for table_name, col_name, task in tasks:
            try:
                await task
            except Exception as exc:
                logger.warning(
                    "Bird-enriched summary failed for %s.%s: %s",
                    table_name, col_name, exc,
                )

        logger.info("BirdEnricher: %d LLM calls", len(tasks))
        return profile, len(tasks)

    async def _enrich_one(
        self,
        table_name: str,
        col: ColumnProfile,
        bird_desc: str,
    ) -> None:
        prompt = self._tmpl.render(
            table_name=table_name,
            column_name=col.name,
            column_type=col.type,
            short_summary=col.short_summary,
            semantic_hint=col.quirks.semantic_hint,
            enum_labels=json.dumps(col.quirks.enum_labels) if col.quirks.enum_labels else "",
            type_mismatch=col.quirks.type_mismatch or "",
            aliases=col.quirks.aliases,
            bird_description=bird_desc,
            sample_values=", ".join(str(v) for v in col.stats.sample_values[:15]),
            distinct_count=col.stats.distinct_count,
            min_value=col.stats.min_value or "?",
            max_value=col.stats.max_value or "?",
        )
        async with self._sem:
            raw = await self._llm.async_generate(prompt)
        text = (raw or "").strip()
        if text:
            col.bird_enriched_summary = text
            logger.debug(
                "bird_enriched for %s.%s: %s", table_name, col.name, text[:80]
            )
