import asyncio
import logging
import random
from typing import Any, Callable

from google import genai
from google.genai import types
from .base import BaseLLM

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3    # total attempts = 4 (1 initial + 3 retries)
_BASE_DELAY = 1.0   # seconds; doubles each retry (1s → 2s → 4s) plus jitter


async def _with_retry(coro_fn, label: str):
    """Call coro_fn() with exponential backoff, retrying up to _MAX_RETRIES times.

    coro_fn must be a zero-argument async callable (use a lambda or nested def).
    Raises the last exception if all retries are exhausted.
    """
    for attempt in range(1, _MAX_RETRIES + 2):  # attempts 1..4
        try:
            return await coro_fn()
        except Exception as exc:
            if attempt == _MAX_RETRIES + 1:
                logger.error(
                    "LLM call [%s] failed after %d attempts — giving up: %s",
                    label, _MAX_RETRIES + 1, exc,
                )
                raise
            delay = _BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "LLM call [%s] attempt %d/%d failed — retrying in %.1fs: %s",
                label, attempt, _MAX_RETRIES + 1, delay, exc,
            )
            await asyncio.sleep(delay)


class GeminiLLM(BaseLLM):
    """Gemini implementation of BaseLLM using the google-genai SDK."""

    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite-preview", thinking_level: str = ""):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._embed_model = "gemini-embedding-001"
        # Build a reusable GenerateContentConfig if thinking is configured.
        # Empty string means "don't send thinking_config at all" (model default).
        if thinking_level:
            self._gen_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=thinking_level)
            )
        else:
            self._gen_config = None

    # --- Synchronous ---

    def _build_config(self, **kwargs) -> types.GenerateContentConfig | None:
        """Merge optional kwargs (e.g. temperature) into the generation config."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return self._gen_config
        thinking_cfg = self._gen_config.thinking_config if self._gen_config else None
        return types.GenerateContentConfig(
            temperature=temperature,
            thinking_config=thinking_cfg,
        )

    def generate(self, prompt: str, timeout: float = 120.0, **kwargs) -> str:
        """Send a prompt to Gemini and return the generated text.

        Raises TimeoutError if the API call exceeds `timeout` seconds (default 120s).
        Note: uses shutdown(wait=False) so the timeout actually fires — the underlying
        thread may linger until the OS-level TCP connection times out, but the caller
        proceeds immediately.
        """
        config = self._build_config(**kwargs)
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            self._client.models.generate_content,
            model=self._model,
            contents=prompt,
            config=config,
        )
        try:
            response = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False)  # don't block on the stuck thread
            logger.error(
                "generate: model=%s timed out after %.0fs — skipping",
                self._model, timeout,
            )
            raise TimeoutError(f"Gemini API call timed out after {timeout:.0f}s")
        executor.shutdown(wait=False)
        m = response.usage_metadata
        self._record_tokens(m.prompt_token_count or 0, m.candidates_token_count or 0)
        logger.debug(
            "generate: model=%s in_tokens=%s out_tokens=%s",
            self._model, m.prompt_token_count, m.candidates_token_count,
        )
        return response.text

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], Any],
        max_turns: int = 3,
        **kwargs,
    ) -> str:
        """Multi-turn generation with function calling.

        Sends the prompt with tool declarations. When the model responds with a
        function call, invokes tool_handler and feeds the result back. Loops
        until the model returns a text response or max_turns is reached.
        """
        # Build function declarations from tool dicts
        func_decls = []
        for t in tools:
            func_decls.append(types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t.get("parameters"),
            ))
        tool_config = types.Tool(functionDeclarations=func_decls)

        config = self._build_config(**kwargs)
        if config:
            config = types.GenerateContentConfig(
                tools=[tool_config],
                thinking_config=config.thinking_config if config else None,
                temperature=getattr(config, "temperature", None),
            )
        else:
            config = types.GenerateContentConfig(tools=[tool_config])

        # Build conversation history
        contents: list[types.Content] = [
            types.Content(role="user", parts=[types.Part(text=prompt)])
        ]

        for turn in range(max_turns + 1):
            import concurrent.futures
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                self._client.models.generate_content,
                model=self._model,
                contents=contents,
                config=config,
            )
            try:
                response = future.result(timeout=120.0)
            except concurrent.futures.TimeoutError:
                executor.shutdown(wait=False)
                logger.error("generate_with_tools: timed out on turn %d", turn)
                raise TimeoutError("Gemini API call timed out")
            executor.shutdown(wait=False)

            m = response.usage_metadata
            self._record_tokens(m.prompt_token_count or 0, m.candidates_token_count or 0)

            # Check if model returned a function call
            candidate = response.candidates[0]
            func_call = None
            text_parts = []
            for part in candidate.content.parts:
                if part.function_call:
                    func_call = part.function_call
                elif part.text:
                    text_parts.append(part.text)

            if func_call is None:
                # No tool call — model is done
                return "\n".join(text_parts) if text_parts else ""

            # Execute the tool
            tool_name = func_call.name
            tool_args = dict(func_call.args) if func_call.args else {}
            logger.info("generate_with_tools: model called %s (turn %d/%d)", tool_name, turn + 1, max_turns)

            try:
                result = tool_handler(tool_name, tool_args)
            except Exception as exc:
                result = f"Error: {exc}"

            result_str = str(result) if not isinstance(result, str) else result

            # Append model's response and tool result to conversation
            contents.append(candidate.content)
            contents.append(types.Content(
                role="user",
                parts=[types.Part(functionResponse=types.FunctionResponse(
                    name=tool_name,
                    response={"result": result_str},
                ))],
            ))

        # Exhausted turns — return whatever text we have
        logger.warning("generate_with_tools: exhausted %d turns, returning last text", max_turns)
        return "\n".join(text_parts) if text_parts else ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for each text, called sequentially."""
        logger.debug(
            "embed: %d texts, ~%d chars total (sequential; token count not provided by embed API)",
            len(texts), sum(len(t) for t in texts),
        )
        results = []
        for text in texts:
            response = self._client.models.embed_content(
                model=self._embed_model,
                contents=text,
            )
            results.append(response.embeddings[0].values)
        return results

    # --- Async ---

    async def async_generate(self, prompt: str, **kwargs) -> str:
        """Async send a prompt to Gemini, with automatic retry on transient failures."""
        config = self._build_config(**kwargs)
        async def _call():
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=config,
            )
            m = response.usage_metadata
            self._record_tokens(m.prompt_token_count or 0, m.candidates_token_count or 0)
            logger.debug(
                "async_generate: model=%s in_tokens=%s out_tokens=%s",
                self._model, m.prompt_token_count, m.candidates_token_count,
            )
            return response.text

        return await _with_retry(_call, label=f"async_generate({self._model})")

    async def async_embed(self, texts: list[str]) -> list[list[float]]:
        """Embed all texts concurrently. Each text retries independently on failure.

        Returns a list parallel to `texts`. Failed texts (all retries exhausted)
        are represented as an empty list [] so callers can detect and skip them.
        """
        logger.debug(
            "async_embed: %d texts, ~%d chars total",
            len(texts), sum(len(t) for t in texts),
        )

        async def _embed_one(text: str, idx: int) -> list[float]:
            async def _call():
                r = await self._client.aio.models.embed_content(
                    model=self._embed_model,
                    contents=text,
                )
                return list(r.embeddings[0].values)
            return await _with_retry(_call, label=f"async_embed[{idx}]({text[:30]!r})")

        results = await asyncio.gather(
            *[_embed_one(t, i) for i, t in enumerate(texts)],
            return_exceptions=True,
        )

        embeddings: list[list[float]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "async_embed: text[%d] failed after all retries — returning [] sentinel: %s",
                    i, result,
                )
                embeddings.append([])
            else:
                embeddings.append(result)
        return embeddings
