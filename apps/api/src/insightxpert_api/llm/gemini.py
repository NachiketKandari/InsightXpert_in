"""Gemini implementation of ``BaseLLM``. Uses the official ``google-genai`` SDK."""

from __future__ import annotations

from google import genai

from .base import BaseLLM


class GeminiLLM(BaseLLM):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        embed_model: str = "gemini-embedding-001",
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._embed_model = embed_model

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
