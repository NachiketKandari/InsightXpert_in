"""NL → SQL generator for automation authoring.

Standalone helper. Intentionally simple: a single-shot prompt against the
greenfield LLM. The result is returned as-is; FE is responsible for letting
the user review/edit before creating the automation.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("insightxpert_api.automations.ai_sql")

_SYSTEM_PROMPT = """\
You are a SQL generator. Generate a single SELECT statement answering the user's prompt.

Rules:
- Output ONLY a JSON object: {"sql": "<query>", "explanation": "<one-line>"}
- No markdown, no fences, no prose outside the JSON.
- SELECT statements only — never INSERT / UPDATE / DELETE / DDL.
- End the SQL with no trailing semicolon.
"""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


async def generate_sql(llm, prompt: str) -> dict:
    """Call the LLM and return ``{"sql": str, "explanation": str | None}``.

    Raises ``ValueError`` if the LLM output cannot be parsed into a SQL string.
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    resp = await llm.chat(messages)
    content = getattr(resp, "content", None) or ""
    cleaned = _strip_code_fences(content)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("ai_sql: LLM returned non-JSON: %s", cleaned[:200])
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    sql = parsed.get("sql") if isinstance(parsed, dict) else None
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("LLM did not return a non-empty 'sql' field")

    return {
        "sql": sql.strip().rstrip(";"),
        "explanation": parsed.get("explanation"),
    }


__all__ = ["generate_sql"]
