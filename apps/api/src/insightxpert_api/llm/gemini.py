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
        return await self._chat_impl.chat(
            messages, tools=tools, force_tool_use=force_tool_use
        )

    # ------------------------------------------------------------------
    # Legacy Phase A pipeline surface (generate / embed)
    # ------------------------------------------------------------------

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
        return resp.text or ""

    def embed(self, text: str) -> list[float]:
        resp = self._client.models.embed_content(model=self._embed_model, contents=text)
        return list(resp.embeddings[0].values)

    async def async_embed(self, text: str) -> list[float]:
        resp = await self._client.aio.models.embed_content(
            model=self._embed_model, contents=text
        )
        return list(resp.embeddings[0].values)
