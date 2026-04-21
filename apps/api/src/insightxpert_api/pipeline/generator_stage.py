"""SqlGeneratorStage — render the clean SQL-generation prompt and parse a fenced block."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Template

from ..llm import LLMProvider
from ..sse.chunks import ChunkType, SQLGeneratedPayload
from .stage import PipelineContext

_FENCED_SQL = re.compile(r"```sql\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


class SqlGeneratorStage:
    """Produce a single SQL query from ``(question, schema_text)``."""

    name = "sql_generator"

    def __init__(self, llm: LLMProvider, prompt_path: str) -> None:
        self._llm = llm
        self._tpl = Template(Path(prompt_path).read_text())

    async def run(self, ctx: PipelineContext, _: object) -> str:
        prompt = self._tpl.render(
            question=ctx.state["question"],
            schema_text=ctx.state["schema_text"],
        )
        resp = await self._llm.async_generate(prompt)
        m = _FENCED_SQL.search(resp)
        sql = (m.group(1) if m else resp).strip().rstrip(";").strip()
        if ctx.emitter is not None:
            await ctx.emitter.emit(
                ChunkType.SQL_GENERATED, SQLGeneratedPayload(sql=sql, iteration=0)
            )
        ctx.state["sql"] = sql
        return sql
