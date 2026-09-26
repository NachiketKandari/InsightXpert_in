"""OpenRouter LLM provider — OpenAI-compatible, model-agnostic.

OpenRouter (https://openrouter.ai/api/v1) fronts 100+ models behind one
OpenAI-compatible endpoint. Model selection is env-driven
(OPENROUTER_CHAT_MODEL) so free-tier rotation needs no code change.
"""

from __future__ import annotations

import logging
import time
import uuid

from openai import AsyncOpenAI

from .base import LLMResponse, ToolCall, log_llm_response

logger = logging.getLogger("insightxpert.llm.openrouter")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    """LLM provider wrapping the OpenAI SDK pointed at OpenRouter's API."""

    def __init__(
        self,
        api_key: str,
        model: str = "nvidia/nemotron-3-ultra-550b-a55b:free",
        base_url: str = OPENROUTER_BASE_URL,
        site_url: str = "",
        app_name: str = "InsightXpert",
    ) -> None:
        if not api_key:
            raise ValueError("openrouter_api_key is required for the openrouter provider")
        base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        default_headers: dict[str, str] = {}
        if site_url:
            default_headers["HTTP-Referer"] = site_url
        if app_name:
            default_headers["X-Title"] = app_name
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, default_headers=default_headers or None
        )
        logger.debug("OpenRouterProvider initialized (model=%s, base_url=%s)", model, base_url)

    @property
    def model(self) -> str:
        return self._model

    def _convert_tools(self, tools: list[dict] | None) -> list[dict] | None:
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
            kwargs["tool_choice"] = "auto"

        start = time.time()
        response = await self._client.chat.completions.create(**kwargs)
        ms = (time.time() - start) * 1000

        # OpenRouter may return choices=None (e.g. filtered/empty completion).
        choices = response.choices or []
        if not choices:
            parsed = LLMResponse(content="", tool_calls=[], input_tokens=0, output_tokens=0)
            log_llm_response(logger, ms, parsed)
            return parsed
        choice = choices[0]
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
