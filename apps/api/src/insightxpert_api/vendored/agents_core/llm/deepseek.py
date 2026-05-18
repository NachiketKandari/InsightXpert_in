"""DeepSeek LLM provider — native OpenAI-compatible format, no translation needed.

DeepSeek's API is OpenAI-compatible, so messages flow through as-is. Tool
definitions and responses follow the standard OpenAI function-calling shape.
"""

from __future__ import annotations

import logging
import time
import uuid

from openai import AsyncOpenAI

from .base import LLMResponse, ToolCall, log_llm_response

logger = logging.getLogger("insightxpert.llm.deepseek")

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider:
    """LLM provider wrapping the OpenAI SDK pointed at DeepSeek's API.

    Implements the ``LLMProvider`` protocol defined in ``llm/base.py``.
    Messages and tools are already in OpenAI format — no conversion needed.
    """

    def __init__(self, api_key: str, model: str = "deepseek-v4-flash") -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        logger.debug("DeepSeekProvider initialized (model=%s)", model)

    @property
    def model(self) -> str:
        return self._model

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
        """Convert our tool dicts to OpenAI function-calling format.

        Our tool dicts have ``name``, ``description``, ``parameters`` at the
        top level; OpenAI expects them wrapped in ``{"type": "function",
        "function": {...}}``.
        """
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        force_tool_use: bool = False,
    ) -> LLMResponse:
        msg_count = len(messages)
        tool_count = len(tools) if tools else 0
        logger.debug(
            "chat() messages=%d tools=%d force_tool=%s model=%s",
            msg_count, tool_count, force_tool_use, self._model,
        )

        openai_tools = self._convert_tools(tools)
        kwargs: dict = {"model": self._model, "messages": messages}
        if openai_tools:
            kwargs["tools"] = openai_tools
        if force_tool_use and openai_tools:
            kwargs["tool_choice"] = "required"

        start = time.time()
        response = await self._client.chat.completions.create(**kwargs)
        ms = (time.time() - start) * 1000

        choice = response.choices[0]
        content = choice.message.content
        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                import json
                args = {}
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    pass
                tool_calls.append(ToolCall(
                    id=tc.id or str(uuid.uuid4())[:8],
                    name=tc.function.name,
                    arguments=args,
                ))

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        parsed = LLMResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        log_llm_response(logger, ms, parsed)
        return parsed
