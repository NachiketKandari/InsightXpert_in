"""LLM provider surface.

The Protocol contract lives in the vendored ``agents_core`` tree (matches
public's shape, which every vendored agent depends on). Our concrete Gemini
adapter lives in ``gemini`` and satisfies both:

- Vendored ``LLMProvider`` Protocol (``model`` property + async ``chat``),
  used by vendored orchestrator / quant_analyst.
- Legacy ``generate`` / ``embed`` surface used by our Phase A pipeline
  stages (linker, generator, refiner, profiler).

The old ``BaseLLM`` ABC is retired; pipeline stages now type-hint against the
vendored ``LLMProvider`` Protocol (structural) or ``GeminiLLM`` directly
when the legacy ``generate``/``embed`` methods are required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..vendored.agents_core.llm.base import LLMProvider, LLMResponse, ToolCall
from .gemini import GeminiLLM
from .deepseek import DeepSeekLLM

if TYPE_CHECKING:
    from ..config import Settings

__all__ = [
    "GeminiLLM",
    "DeepSeekLLM",
    "LLMProvider",
    "LLMResponse",
    "ToolCall",
    "create_chat_llm",
]


def create_chat_llm(settings: "Settings") -> GeminiLLM | DeepSeekLLM:
    """Create the correct LLM adapter based on ``settings.llm_provider``."""
    if getattr(settings, "llm_provider", None) == "deepseek":
        return DeepSeekLLM(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_chat_model,
            embed_api_key=settings.gemini_api_key,
            embed_model=settings.gemini_embed_model,
        )
    return GeminiLLM(
        api_key=settings.gemini_api_key,
        model=settings.gemini_chat_model,
        embed_model=settings.gemini_embed_model,
    )
