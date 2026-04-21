"""Claude Code CLI wrapper — uses `claude -p` for text generation.

Requires a Claude Code Max subscription (no API credits needed).
Each call spawns a fresh `claude -p` process with --no-session-persistence.
"""
import asyncio
import json
import logging
import subprocess
import time

from typing import Any, Callable

from .base import BaseLLM

logger = logging.getLogger(__name__)


class ClaudeLLM(BaseLLM):
    """Claude implementation of BaseLLM using the Claude Code CLI."""

    def __init__(self, model: str = "sonnet", allow_tools: bool = False):
        self._model = model
        self._allow_tools = allow_tools
        self._total_cost = 0.0

    def generate(self, prompt: str, timeout: float = 180.0, **kwargs) -> str:
        """Send a prompt to Claude via CLI and return the generated text."""
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--model", self._model,
            "--no-session-persistence",
        ]
        if not self._allow_tools:
            cmd += ["--tools", ""]

        logger.debug("Calling claude -p (model=%s, timeout=%.0fs)", self._model, timeout)
        start = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            logger.error("Claude CLI timed out after %.0fs", elapsed)
            raise TimeoutError(f"Claude CLI timed out after {elapsed:.0f}s")

        elapsed = time.time() - start

        if result.returncode != 0 and not result.stdout.strip():
            logger.error("Claude CLI failed (rc=%d): %s", result.returncode, result.stderr[:500])
            raise RuntimeError(f"Claude CLI exit code {result.returncode}: {result.stderr[:500]}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error("Failed to parse Claude CLI JSON output: %s", result.stdout[:500])
            raise RuntimeError(f"Invalid JSON from Claude CLI: {result.stdout[:200]}")

        if data.get("is_error"):
            raise RuntimeError(f"Claude CLI error: {data.get('result', 'unknown')}")

        # Track usage
        cost = data.get("total_cost_usd", 0)
        usage = data.get("usage", {})
        in_tokens = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        out_tokens = usage.get("output_tokens", 0)

        self._total_cost += cost
        self._record_tokens(in_tokens, out_tokens)

        logger.info(
            "Claude response: model=%s, %.1fs, %d in + %d out tokens, $%.4f",
            self._model, elapsed, in_tokens, out_tokens, cost,
        )

        return data.get("result", "")

    async def async_generate(self, prompt: str, **kwargs) -> str:
        """Async wrapper — runs claude -p in a subprocess."""
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--model", self._model,
            "--no-session-persistence",
        ]
        if not self._allow_tools:
            cmd += ["--tools", ""]

        logger.debug("async_generate: claude -p (model=%s)", self._model)
        start = time.time()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = time.time() - start
            logger.error("Claude CLI timed out after %.0fs", elapsed)
            raise TimeoutError(f"Claude CLI timed out after {elapsed:.0f}s")

        elapsed = time.time() - start
        stdout_str = stdout.decode()
        stderr_str = stderr.decode()

        if proc.returncode != 0 and not stdout_str.strip():
            logger.error("Claude CLI failed (rc=%d): %s", proc.returncode, stderr_str[:500])
            raise RuntimeError(f"Claude CLI exit code {proc.returncode}: {stderr_str[:500]}")

        try:
            data = json.loads(stdout_str)
        except json.JSONDecodeError:
            logger.error("Failed to parse Claude CLI JSON: %s", stdout_str[:500])
            raise RuntimeError(f"Invalid JSON from Claude CLI: {stdout_str[:200]}")

        if data.get("is_error"):
            raise RuntimeError(f"Claude CLI error: {data.get('result', 'unknown')}")

        cost = data.get("total_cost_usd", 0)
        usage = data.get("usage", {})
        in_tokens = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        out_tokens = usage.get("output_tokens", 0)

        self._total_cost += cost
        self._record_tokens(in_tokens, out_tokens)

        logger.info(
            "async Claude response: model=%s, %.1fs, %d in + %d out tokens, $%.4f",
            self._model, elapsed, in_tokens, out_tokens, cost,
        )

        return data.get("result", "")

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], Any],
        max_turns: int = 3,
        **kwargs,
    ) -> str:
        """Tool calling not supported via CLI — fall back to plain generate."""
        logger.warning("generate_with_tools: Claude CLI does not support tool calling, falling back to plain generate")
        return self.generate(prompt, **kwargs)

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Claude does not support embeddings. Use --perfect-linking to bypass embedding-based schema linking."
        )

    async def async_embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Claude does not support embeddings. Use --perfect-linking to bypass embedding-based schema linking."
        )

    @property
    def total_cost(self) -> float:
        return self._total_cost
