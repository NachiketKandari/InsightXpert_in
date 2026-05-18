"""DeepSeek LLM adapter — satisfies the vendored LLMProvider Protocol + legacy surface.

Matches the GeminiLLM shape so pipeline stages and the orchestrator can consume
either adapter without code changes.

DeepSeek does not offer an embeddings API, so ``embed``/``async_embed`` delegate
to Gemini's embedding endpoint (``gemini-embedding-001``). A Gemini API key is
required for those calls even when the chat provider is DeepSeek.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from google import genai
from openai import AsyncOpenAI

from ..vendored.agents_core.llm.base import LLMResponse
from ..vendored.agents_core.llm.deepseek import DeepSeekProvider as _VendoredDeepSeek

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# --------------------------------------------------------------------------
# Global LLM concurrency cap — mirror of llm/gemini.py's semaphore.
# Both modules share the same env var and the same mechanism.
# --------------------------------------------------------------------------

_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _llm_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        cap = int(os.environ.get("LLM_MAX_CONCURRENCY", "3") or 3)
        _LLM_SEMAPHORE = asyncio.Semaphore(max(1, cap))
    return _LLM_SEMAPHORE


def _reset_llm_semaphore(n: int) -> None:
    global _LLM_SEMAPHORE
    _LLM_SEMAPHORE = asyncio.Semaphore(max(1, int(n)))


class DeepSeekLLM:
    """Concrete LLM conforming to the vendored ``LLMProvider`` Protocol.

    Exposes the legacy ``generate``/``async_generate``/``async_generate_stream``
    surface used by Phase A pipeline stages, plus the ``chat`` method required
    by the vendored orchestrator and quant_analyst.

    Embeddings delegate to Gemini's embedding-001 model.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        embed_api_key: str = "",
        embed_model: str = "gemini-embedding-001",
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        self._model = model
        self._embed_model = embed_model
        self._embed_client = genai.Client(api_key=embed_api_key) if embed_api_key else None
        self._chat_impl = _VendoredDeepSeek(api_key=api_key, model=model)
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
        self.input_tokens_used += int(resp.input_tokens or 0)
        self.output_tokens_used += int(resp.output_tokens or 0)
        return resp

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
        raise NotImplementedError("DeepSeekLLM does not support sync generate — use async_generate")

    async def async_generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        async with _llm_semaphore():
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        usage = response.usage
        if usage:
            self.input_tokens_used += usage.prompt_tokens or 0
            self.output_tokens_used += usage.completion_tokens or 0
        return response.choices[0].message.content or ""

    async def async_generate_stream(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream text from DeepSeek, yielding incremental deltas."""
        async with _llm_semaphore():
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                choices = chunk.choices
                if not choices:
                    # Final usage chunk — choices is empty, usage is populated.
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        self.input_tokens_used += chunk.usage.prompt_tokens or 0
                        self.output_tokens_used += chunk.usage.completion_tokens or 0
                    continue
                choice = choices[0]
                # DeepSeek V4 can return reasoning_content in thinking mode — skip
                # it so the FE sees only the final answer text.
                delta = choice.delta if choice else None
                if delta and delta.content:
                    yield delta.content
                # Belt-and-suspenders: also check for usage on non-empty choice chunks.
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    self.input_tokens_used += chunk.usage.prompt_tokens or 0
                    self.output_tokens_used += chunk.usage.completion_tokens or 0

    def embed(self, text: str) -> list[float]:
        if not self._embed_client:
            raise RuntimeError(
                "DeepSeekLLM requires embed_api_key for embeddings (Gemini embed-001)"
            )
        resp = self._embed_client.models.embed_content(
            model=self._embed_model, contents=text
        )
        return list(resp.embeddings[0].values)

    async def async_embed(self, text: str) -> list[float]:
        if not self._embed_client:
            raise RuntimeError(
                "DeepSeekLLM requires embed_api_key for embeddings (Gemini embed-001)"
            )
        resp = await self._embed_client.aio.models.embed_content(
            model=self._embed_model, contents=text
        )
        return list(resp.embeddings[0].values)
