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

from ..vendored.agents_core.llm.base import LLMProvider, LLMResponse, ToolCall
from .gemini import GeminiLLM

__all__ = ["GeminiLLM", "LLMProvider", "LLMResponse", "ToolCall"]
