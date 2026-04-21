"""Provider-agnostic LLM interface. Every pipeline stage depends on this ABC, not concretes."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """Minimal LLM contract: sync + async generate, sync + async embed."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str: ...

    @abstractmethod
    async def async_generate(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str: ...

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    @abstractmethod
    async def async_embed(self, text: str) -> list[float]: ...
