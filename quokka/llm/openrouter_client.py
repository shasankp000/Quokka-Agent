"""
OpenRouter LLM client for cloud inference
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import Message, ToolCall
from .base import BaseLLM

logger = get_logger(__name__)


class OpenRouterLLM(BaseLLM):
    """
    OpenRouter cloud LLM client

    Supports:
    - Multiple LLM providers through OpenRouter API
    - Tool/function calling
    - Streaming responses
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize OpenRouter client

        Args:
            api_key: OpenRouter API key (defaults to config or env)
            model: Model name (defaults to config)
        """
        config = get_config()
        self.api_key = api_key or config.openrouter.api_key
        self._model = model or config.openrouter.model
        self.base_url = config.openrouter.base_url
        self.timeout = config.openrouter.timeout
        self.temperature = config.openrouter.temperature

        self._client = httpx.AsyncClient(timeout=self.timeout)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "openrouter"

    async def is_available(self) -> bool:
        """Check if OpenRouter is accessible"""
        if not self.api_key:
            return False
        try:
            response = await self._client.get(
                f"{self.base_url}/models",
                headers=self._get_headers(),
            )
            return response.status_code == 200
        except Exception:
            return False

    def _get_headers(self) -> dict[str, str]:
        """Get API headers"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/quokka-agent",  # Optional, for rankings
            "X-Title": "Quokka Agent",  # Optional, for rankings
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> tuple[str, list[ToolCall]]:
        """
        Generate a chat completion via OpenRouter

        Args:
            messages: List of messages in the conversation
            tools: List of available tools (function schemas)
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate

        Returns:
            Tuple of (response_text, tool_calls)
        """
        openai_messages = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)
            payload["tool_choice"] = "auto"

        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})

            text = message.get("content", "") or ""
            tool_calls = self._parse_tool_calls(message.get("tool_calls", []))

            return text, tool_calls

        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error: {e}")
            if e.response.status_code == 401:
                raise ValueError("Invalid OpenRouter API key")
            raise
        except Exception as e:
            logger.error(f"OpenRouter request failed: {e}")
            raise

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """
        Generate a streaming chat completion via OpenRouter

        Yields chunks of the response text
        """
        openai_messages = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)
            payload["tool_choice"] = "auto"

        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload,
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"OpenRouter streaming failed: {e}")
            raise

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert Quokka messages to OpenAI format"""
        result = []
        for msg in messages:
            openai_msg = msg.to_openai_format()
            result.append(openai_msg)

            # Handle tool results (as separate messages)
            for tr in msg.tool_results:
                result.append({
                    "role": "tool",
                    "tool_call_id": tr.call_id,
                    "content": json.dumps(tr.output) if isinstance(tr.output, dict) else str(tr.output),
                })

        return result

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tool schemas to OpenAI format"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                },
            }
            for tool in tools
        ]

    def _parse_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """Parse OpenAI tool calls to ToolCall objects"""
        result = []
        for tc in tool_calls:
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            result.append(ToolCall(
                id=tc.get("id", f"call_{len(result)}"),
                name=func.get("name", ""),
                arguments=args,
            ))
        return result

    async def close(self) -> None:
        """Close the HTTP client"""
        await self._client.aclose()
