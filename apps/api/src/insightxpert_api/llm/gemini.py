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

from google import genai

from ..vendored.agents_core.llm.base import LLMResponse
from ..vendored.agents_core.llm.gemini import GeminiProvider as _VendoredGemini


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
        self._client = genai.Client(api_key=api_key)
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
        resp = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        self._record_usage(resp)
        return resp.text or ""

    def embed(self, text: str) -> list[float]:
        resp = self._client.models.embed_content(model=self._embed_model, contents=text)
        return list(resp.embeddings[0].values)

    async def async_embed(self, text: str) -> list[float]:
        resp = await self._client.aio.models.embed_content(
            model=self._embed_model, contents=text
        )
        return list(resp.embeddings[0].values)
