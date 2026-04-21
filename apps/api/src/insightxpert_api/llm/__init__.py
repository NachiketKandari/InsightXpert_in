"""LLM abstraction: provider-agnostic ABC + default Gemini implementation."""

from .base import BaseLLM
from .gemini import GeminiLLM

__all__ = ["BaseLLM", "GeminiLLM"]
