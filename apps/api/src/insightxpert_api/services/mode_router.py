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
from ..vendored.agents_core.common import strip_json_fences

log = get_logger("mode_router")

Mode = Literal["basic", "agentic"]

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "mode_router.j2"
)
_TEMPLATE = Template(_PROMPT_PATH.read_text())

# Cached clients — reused across calls so we don't pay DNS+TLS+TCP per
# classification. Reset in tests via _reset_mode_router_clients().
_deepseek_client: "AsyncOpenAI | None" = None
_gemini_client: "genai.Client | None" = None


# TEST-ONLY
def _reset_mode_router_clients() -> None:
    """Test hook: discard cached clients so tests can inject fresh ones."""
    global _deepseek_client, _gemini_client
    _deepseek_client = None
    _gemini_client = None


# Gemini Flash-Lite is purpose-built for low-latency classification. We force
# this regardless of ``settings.gemini_chat_model`` because the router runs on
# the critical-path before any pipeline activity is visible to the user, and
# spending the user's chosen-model latency budget here would defeat the point.
# When the provider is DeepSeek, we use deepseek-v4-flash with JSON mode instead.
_ROUTER_MODEL_GEMINI = "gemini-3.1-flash-lite-preview"
_ROUTER_MODEL_DEEPSEEK = "deepseek-v4-flash"

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


async def _classify_via_deepseek(prompt: str, settings: Settings) -> str:
    """Classify using DeepSeek V4 Flash with JSON mode."""
    global _deepseek_client
    if _deepseek_client is None:
        from openai import AsyncOpenAI
        _deepseek_client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
        )
    resp = await _deepseek_client.chat.completions.create(
        model=_ROUTER_MODEL_DEEPSEEK,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=128,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


async def _classify_via_gemini(prompt: str, settings: Settings) -> str:
    """Classify using Gemini Flash-Lite with native JSON mode."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.0,
        max_output_tokens=128,
    )
    resp = await _gemini_client.aio.models.generate_content(
        model=_ROUTER_MODEL_GEMINI,
        contents=prompt,
        config=config,
    )
    return (resp.text or "").strip()


async def classify_mode(
    *,
    question: str,
    db_id: str,
    settings: Settings,
) -> RouteDecision:
    """Classify a single user question.

    Always returns a ``RouteDecision`` — never raises. Errors are logged and
    fall back to ``agentic``.

    Uses the configured ``llm_provider`` for the classification call:
      - ``"deepseek"`` → deepseek-v4-flash with JSON mode
      - ``"gemini"`` or anything else → gemini-3.1-flash-lite-preview
    """
    prompt = _TEMPLATE.render(question=question, db_id=db_id)

    start = time.monotonic()
    try:
        if settings.llm_provider == "deepseek":
            text = await _classify_via_deepseek(prompt, settings)
        else:
            text = await _classify_via_gemini(prompt, settings)
        text = text.strip()
    except Exception as exc:  # noqa: BLE001 — defense in depth
        log.warning("mode_router api_error error=%s", exc)
        return _fallback()

    latency_ms = int((time.monotonic() - start) * 1000)

    try:
        parsed = json.loads(strip_json_fences(text))
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
