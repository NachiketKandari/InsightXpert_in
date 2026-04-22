"""Compile a natural-language trigger description into a TriggerCondition dict.

Uses the greenfield LLM module (``..llm``). Returns a dict matching the
``TriggerCondition`` shape (no ``slope``). On parse failure callers should fall
back to a plain threshold template — see ``DEFAULT_FALLBACK``.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("insightxpert_api.automations.nl_trigger")

_VALID_TYPES = {
    "threshold",
    "row_count",
    "change_detection",
    "column_expression",
}

DEFAULT_FALLBACK: dict = {
    "type": "threshold",
    "operator": "gt",
    "value": 0,
}


_SYSTEM_PROMPT = """\
You are a trigger condition compiler. The user describes a trigger condition in plain English.
You must output ONLY a JSON object (no markdown, no explanation) representing one trigger condition.

The JSON must have a "type" field that is one of:
- "threshold" — compare a single value against a threshold
- "row_count" — compare the number of result rows
- "change_detection" — fire when value changes by N% from previous run
- "column_expression" — check a column value across rows

Fields per type:
- threshold: {{ "type": "threshold", "column": "<col_name or null>", "operator": "<gt|gte|lt|lte|eq|ne>", "value": <number> }}
- row_count: {{ "type": "row_count", "operator": "<gt|gte|lt|lte|eq|ne>", "value": <number> }}
- change_detection: {{ "type": "change_detection", "column": "<col_name or null>", "change_percent": <number> }}
- column_expression: {{ "type": "column_expression", "column": "<col_name>", "operator": "<gt|gte|lt|lte|eq|ne>", "value": <number>, "scope": "<any_row|all_rows>" }}

Available columns: {columns}

Output ONLY the JSON object. No markdown fences, no text before or after.
"""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


async def compile_nl_trigger(
    llm,
    nl_text: str,
    available_columns: list[str] | None = None,
) -> dict:
    """Compile NL trigger → dict. Raises ValueError on unparseable output."""
    columns_str = (
        ", ".join(available_columns) if available_columns else "(not specified)"
    )
    system_prompt = _SYSTEM_PROMPT.format(columns=columns_str)

    response_text = await _call_llm(llm, system_prompt, nl_text)
    cleaned = _strip_code_fences(response_text)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned invalid JSON for NL trigger: %s", cleaned[:200])
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    if not isinstance(result, dict) or result.get("type") not in _VALID_TYPES:
        raise ValueError(
            f"Invalid trigger type: {result.get('type') if isinstance(result, dict) else None}. "
            f"Must be one of: {sorted(_VALID_TYPES)}"
        )

    result["nl_text"] = nl_text
    return result


async def compile_or_fallback(
    llm,
    nl_text: str,
    available_columns: list[str] | None = None,
) -> dict:
    """Compile NL trigger with a threshold fallback on parse failure."""
    try:
        return await compile_nl_trigger(llm, nl_text, available_columns)
    except (ValueError, json.JSONDecodeError) as exc:
        # Narrow catch (MF5): only parse/validation failures fall back to a
        # safe threshold template. Any other exception — LLM provider error,
        # timeout, network failure — must propagate so the route returns 502
        # instead of silently producing a surprise "fire on anything > 0"
        # trigger.
        logger.warning(
            "nl_trigger.parse_failed",
            extra={"reason": str(exc), "nl_text": nl_text},
        )
        fallback = dict(DEFAULT_FALLBACK)
        fallback["nl_text"] = nl_text
        return fallback


async def _call_llm(llm, system_prompt: str, user_message: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    response = await llm.chat(messages)
    return getattr(response, "content", None) or ""


__all__ = ["compile_nl_trigger", "compile_or_fallback", "DEFAULT_FALLBACK"]
