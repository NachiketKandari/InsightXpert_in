"""Gemini implementation that satisfies both legacy and vendored contracts.

The class retains the Phase A ``generate``/``async_generate``/``embed``/
``async_embed`` surface (pipeline stages still depend on it) and additionally
implements the vendored ``LLMProvider`` Protocol (``model`` property + async
``chat``), so the same instance can be handed to the vendored orchestrator
and quant_analyst.

The ``chat`` path delegates to the vendored ``GeminiProvider`` to avoid
duplicating the OpenAI-style <-> Gemini native message translation logic.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from google import genai

from ..vendored.agents_core.llm.base import LLMResponse
from ..vendored.agents_core.llm.gemini import GeminiProvider as _VendoredGemini

# --------------------------------------------------------------------------
# Phase 1.4 — global LLM concurrency cap.
# A single bursty user must not be able to drive Gemini into 429 for every
# other user. One semaphore at module scope, shared across every GeminiLLM
# instance so per-turn adapters all funnel through the same cap. Lazy-init
# so async tests can reset without monkeypatching asyncio internals.
# --------------------------------------------------------------------------

_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _llm_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        cap = int(os.environ.get("LLM_MAX_CONCURRENCY", "3") or 3)
        _LLM_SEMAPHORE = asyncio.Semaphore(max(1, cap))
    return _LLM_SEMAPHORE


def _reset_llm_semaphore(n: int) -> None:
    """Test hook — reset the module-level LLM semaphore."""
    global _LLM_SEMAPHORE
    _LLM_SEMAPHORE = asyncio.Semaphore(max(1, int(n)))


class GeminiLLM:
    """Concrete LLM conforming to the vendored ``LLMProvider`` Protocol.

    Also exposes the legacy ``generate``/``embed`` methods used by our
    Phase A pipeline stages.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        embed_model: str = "gemini-embedding-001",
    ) -> None:
        self._client = genai.Client(api_key=api_key, http_options={"timeout": 120_000})
        self._model = model
        self._embed_model = embed_model
        # Vendored provider reuses the same API key; it maintains its own
        # genai.Client internally for ``chat``. Keeping separate clients
        # keeps the translation logic encapsulated in the vendored module.
        self._chat_impl = _VendoredGemini(api_key=api_key, model=model)
        # Per-instance running totals of Gemini ``usage_metadata`` tokens
        # across every ``chat``/``generate``/``async_generate`` call made on
        # this adapter. A fresh ``GeminiLLM`` is constructed per chat turn
        # (route layer), so these counters naturally scope to a single turn
        # and can be surfaced on the terminal ``metrics`` SSE chunk.
        self.input_tokens_used: int = 0
        self.output_tokens_used: int = 0

    # ------------------------------------------------------------------
    # LLMProvider Protocol surface
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        force_tool_use: bool = False,
    ) -> LLMResponse:
        async with _llm_semaphore():
            resp = await self._chat_impl.chat(
                messages, tools=tools, force_tool_use=force_tool_use
            )
        # Gemini's ``usage_metadata`` is surfaced on LLMResponse by the
        # vendored provider (see vendored/agents_core/llm/gemini.py).
        # Accumulate so the route layer can emit it on the terminal
        # ``metrics`` chunk.
        self.input_tokens_used += int(resp.input_tokens or 0)
        self.output_tokens_used += int(resp.output_tokens or 0)
        return resp

    # ------------------------------------------------------------------
    # Legacy Phase A pipeline surface (generate / embed)
    # ------------------------------------------------------------------

    def _record_usage(self, resp: object) -> None:
        """Fold a Gemini generate_content response's ``usage_metadata`` into
        this adapter's running token totals.

        Older SDK versions / error responses may not carry usage_metadata, so
        we guard on ``getattr`` and fall back to 0. Non-numeric values (rare
        test mocks) are silently ignored.
        """
        usage = getattr(resp, "usage_metadata", None)
        if usage is None:
            return
        try:
            self.input_tokens_used += int(getattr(usage, "prompt_token_count", 0) or 0)
            self.output_tokens_used += int(getattr(usage, "candidates_token_count", 0) or 0)
        except (TypeError, ValueError):
            pass

    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        self._record_usage(resp)
        return resp.text or ""

    async def async_generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        async with _llm_semaphore():
            resp = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config={"temperature": temperature, "max_output_tokens": max_tokens},
            )
        self._record_usage(resp)
        return resp.text or ""

    async def async_generate_stream(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream text from Gemini, yielding incremental deltas as they arrive.

        Mirrors ``async_generate``'s config (temperature, max_tokens) but
        invokes the SDK's ``aio.models.generate_content_stream`` endpoint and
        yields each chunk's text payload (skipping empty chunks). On stream
        completion, the final chunk's ``usage_metadata`` is folded into this
        adapter's running token totals — same accounting as the one-shot path.

        The semaphore is held for the entire stream lifetime so that the
        global LLM concurrency cap reflects in-flight streams, not just
        one-shot calls.
        """
        async with _llm_semaphore():
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=prompt,
                config={"temperature": temperature, "max_output_tokens": max_tokens},
            )
            last_chunk: object | None = None
            async for chunk in stream:
                last_chunk = chunk
                text = getattr(chunk, "text", None)
                if text:
                    yield text
            if last_chunk is not None:
                self._record_usage(last_chunk)

    def embed(self, text: str) -> list[float]:
        resp = self._client.models.embed_content(model=self._embed_model, contents=text)
        return list(resp.embeddings[0].values)

    async def async_embed(self, text: str) -> list[float]:
        resp = await self._client.aio.models.embed_content(
            model=self._embed_model, contents=text
        )
        return list(resp.embeddings[0].values)
