from abc import ABC, abstractmethod
from typing import Any, Callable


class BaseLLM(ABC):
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def reset_token_counts(self) -> None:
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _record_tokens(self, input_count: int, output_count: int) -> None:
        """Record token usage. Safe under CPython GIL for int +=."""
        self.total_input_tokens += input_count
        self.total_output_tokens += output_count

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate a text response for the given prompt."""
        ...

    @abstractmethod
    async def async_generate(self, prompt: str, **kwargs) -> str:
        """Async generate a text response for the given prompt."""
        ...

    @abstractmethod
    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], Any],
        max_turns: int = 3,
        **kwargs,
    ) -> str:
        """Generate with function-calling tools in a multi-turn loop.

        Args:
            prompt: Initial prompt text.
            tools: List of tool declarations (name, description, parameters).
            tool_handler: Callback(tool_name, tool_args) -> result string/dict.
            max_turns: Max tool-call rounds before forcing a text response.

        Returns:
            Final text response from the model.
        """
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for each text."""
        ...

    @abstractmethod
    async def async_embed(self, texts: list[str]) -> list[list[float]]:
        """Async return embeddings for each text."""
        ...
