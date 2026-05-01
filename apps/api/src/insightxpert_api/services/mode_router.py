"""LLM-driven mode router for the auto-mode chat dispatch.

A single Gemini Flash-Lite call classifies a user question as either ``basic``
(one-shot SQL pipeline) or ``agentic`` (multi-step orchestrator). The result
is consumed by:

  - ``POST /api/v1/chat/route``: explicit pre-flight call from the FE so the
    UI can show the routed mode + reason before the heavier ``/chat`` request
    actually starts.
  - ``POST /api/v1/chat`` with ``agent_mode="auto"``: server-side fallback so
    a client that skips ``/route`` is still routed correctly (defense in
    depth — never trust the client).

Output is strict JSON ``{"mode": ..., "reason": ...}`` enforced via Gemini's
``response_mime_type="application/json"``. On any failure (parse error, API
error, unexpected mode value) we default to ``"agentic"`` with a fallback
reason — better to spend an extra orchestrator turn than misroute a complex
question to the basic pipeline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import types
from jinja2 import Template
from pydantic import BaseModel

from ..config import Settings
from ..logging import get_logger

log = get_logger("mode_router")

Mode = Literal["basic", "agentic"]

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "mode_router.j2"
)
_TEMPLATE = Template(_PROMPT_PATH.read_text())

# Gemini Flash-Lite is purpose-built for low-latency classification. We force
# this regardless of ``settings.gemini_chat_model`` because the router runs on
# the critical-path before any pipeline activity is visible to the user, and
# spending the user's chosen-model latency budget here would defeat the point.
_ROUTER_MODEL = "gemini-3.1-flash-lite-preview"


class RouteDecision(BaseModel):
    mode: Mode
    reason: str


def _fallback(reason: str = "fallback (router error)") -> RouteDecision:
    """Default when the router can't make a confident call.

    Prefer agentic — the orchestrator handles simple questions fine; the
    basic pipeline cannot handle complex ones. Bias toward correctness over
    latency on the unhappy path.
    """
    return RouteDecision(mode="agentic", reason=reason)


async def classify_mode(
    *,
    question: str,
    db_id: str,
    settings: Settings,
) -> RouteDecision:
    """Classify a single user question.

    Always returns a ``RouteDecision`` — never raises. Errors are logged and
    fall back to ``agentic``.
    """
    prompt = _TEMPLATE.render(question=question, db_id=db_id)

    start = time.monotonic()
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=128,
        )
        resp = await client.aio.models.generate_content(
            model=_ROUTER_MODEL,
            contents=prompt,
            config=config,
        )
        text = (resp.text or "").strip()
    except Exception as exc:  # noqa: BLE001 — defense in depth
        log.warning("mode_router api_error error=%s", exc)
        return _fallback()

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        parsed = json.loads(text)
        mode = parsed.get("mode")
        reason = str(parsed.get("reason", "")).strip() or "no reason given"
        if mode not in ("basic", "agentic"):
            log.warning("mode_router invalid_mode mode=%s text=%r", mode, text)
            return _fallback("fallback (invalid mode value)")
        log.info(
            "mode_router decided mode=%s latency_ms=%d db_id=%s",
            mode,
            latency_ms,
            db_id,
        )
        return RouteDecision(mode=mode, reason=reason)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        log.warning("mode_router parse_error error=%s text=%r", exc, text)
        return _fallback("fallback (router parse error)")
