"""OpenRouter LLM adapter — satisfies the vendored LLMProvider Protocol + legacy surface.

Mirrors DeepSeekLLM shape so pipeline stages and the orchestrator can consume
either adapter without code changes.

OpenRouter hosts chat models only (no native embeddings), so ``embed`` /
``async_embed`` delegate to Gemini's embedding endpoint. A Gemini API key is
still required for those calls even when the chat provider is OpenRouter.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from google import genai
from openai import AsyncOpenAI

from ..vendored.agents_core.llm.base import LLMResponse
from ..vendored.agents_core.llm.openrouter import OpenRouterProvider as _VendoredOpenRouter

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _llm_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        cap = int(os.environ.get("LLM_MAX_CONCURRENCY", "3") or 3)
        _LLM_SEMAPHORE = asyncio.Semaphore(max(1, cap))
    return _LLM_SEMAPHORE


# TEST-ONLY
def _reset_llm_semaphore(n: int) -> None:
    global _LLM_SEMAPHORE
    _LLM_SEMAPHORE = asyncio.Semaphore(max(1, int(n)))


class OpenRouterLLM:
    """Concrete LLM conforming to the vendored ``LLMProvider`` Protocol."""

    def __init__(
        self,
        api_key: str,
        model: str = "nvidia/nemotron-3-ultra-550b-a55b:free",
        base_url: str = OPENROUTER_BASE_URL,
        site_url: str = "",
        app_name: str = "InsightXpert",
        embed_api_key: str = "",
        embed_model: str = "gemini-embedding-001",
    ) -> None:
        if not api_key:
            raise ValueError("openrouter_api_key is required for the openrouter provider")
        base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        default_headers: dict[str, str] = {}
        if site_url:
            default_headers["HTTP-Referer"] = site_url
        if app_name:
            default_headers["X-Title"] = app_name
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=120.0,
            default_headers=default_headers or None,
        )
        self._model = model
        self._embed_model = embed_model
        self._embed_client = genai.Client(api_key=embed_api_key) if embed_api_key else None
        self._chat_impl = _VendoredOpenRouter(
            api_key=api_key, model=model, base_url=base_url,
            site_url=site_url, app_name=app_name,
        )
        self.input_tokens_used: int = 0
        self.output_tokens_used: int = 0

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

    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        raise NotImplementedError("OpenRouterLLM does not support sync generate — use async_generate")

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
        """Stream text from OpenRouter, yielding incremental deltas."""
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
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        self.input_tokens_used += chunk.usage.prompt_tokens or 0
                        self.output_tokens_used += chunk.usage.completion_tokens or 0
                    continue
                choice = choices[0]
                delta = choice.delta if choice else None
                if delta and delta.content:
                    yield delta.content
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    self.input_tokens_used += chunk.usage.prompt_tokens or 0
                    self.output_tokens_used += chunk.usage.completion_tokens or 0

    def embed(self, text: str) -> list[float]:
        if not self._embed_client:
            raise RuntimeError(
                "OpenRouterLLM requires embed_api_key for embeddings (Gemini embed-001)"
            )
        resp = self._embed_client.models.embed_content(
            model=self._embed_model, contents=text
        )
        return list(resp.embeddings[0].values)

    async def async_embed(self, text: str) -> list[float]:
        if not self._embed_client:
            raise RuntimeError(
                "OpenRouterLLM requires embed_api_key for embeddings (Gemini embed-001)"
            )
        resp = await self._embed_client.aio.models.embed_content(
            model=self._embed_model, contents=text
        )
        return list(resp.embeddings[0].values)
