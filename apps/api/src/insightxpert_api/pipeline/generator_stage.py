"""SqlGeneratorStage — render the SQL-generation prompt (dialect-aware) and parse a fenced block."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Template

from ..db.dialects import get_adapter
from ..llm import LLMProvider
from ..sse.chunks import ChunkType, SQLGeneratedPayload
from .stage import PipelineContext

_FENCED_SQL = re.compile(r"```sql\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)

# Directory that holds our own (non-vendored) prompt overrides.
_OWN_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _prompt_name_for_dialect(dialect: str) -> str:
    """Return prompt name stem (without .j2) based on dialect string.

    SQLite keeps the un-suffixed vendored name so the existing default pipeline
    wiring stays unchanged.  Any other dialect gets a ``sql_generation_{variant}``
    stem looked up in our own prompts directory.
    """
    variant = get_adapter(dialect).prompt_variant
    return "sql_generation" if variant == "sqlite" else f"sql_generation_{variant}"


def _prompt_name_for_ref(ref: object) -> str:
    """Return prompt name stem (without .j2) for a DatabaseRef-like object.

    Accepts any object with a ``.dialect`` attribute; used by tests that pass a
    MagicMock ref.
    """
    dialect: str = getattr(ref, "dialect", "sqlite")
    return _prompt_name_for_dialect(dialect)


class SqlGeneratorStage:
    """Produce a single SQL query from ``(question, schema_text)``."""

    name = "sql_generator"

    def __init__(self, llm: LLMProvider, prompt_path: str) -> None:
        self._llm = llm
        # Default prompt path (vendored SQLite prompt). Used when the dialect
        # resolves to "sqlite" or when no db_dialect is in state.
        self._default_prompt_path = Path(prompt_path)

    def _resolve_template(self, dialect: str) -> Template:
        """Load the prompt template for the given dialect.

        Lookup order:
        1. Our own prompts dir: ``insightxpert_api/prompts/sql_generation_{variant}.j2``
        2. Default (vendored) path passed at construction (sqlite baseline).
        """
        name = _prompt_name_for_dialect(dialect)
        own_path = _OWN_PROMPTS_DIR / f"{name}.j2"
        if own_path.exists():
            return Template(own_path.read_text())
        # Fall back to the default prompt (vendored SQLite template).
        return Template(self._default_prompt_path.read_text())

    async def run(self, ctx: PipelineContext, _: object) -> str:
        dialect: str = ctx.state.get("db_dialect", "sqlite")
        tpl = self._resolve_template(dialect)
        prompt = tpl.render(
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
