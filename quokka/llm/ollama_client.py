"""
Ollama LLM client for local inference
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


class OllamaLLM(BaseLLM):
    """
    Ollama local LLM client

    Supports:
    - Local inference via Ollama API
    - Tool/function calling (with supported models)
    - Streaming responses
    """

    def __init__(self, base_url: str | None = None, model: str | None = None):
        """
        Initialize Ollama client

        Args:
            base_url: Ollama API URL (defaults to config)
            model: Model name (defaults to config)
        """
        config = get_config()
        self.base_url = base_url or config.ollama.base_url
        self._model = model or config.ollama.model
        self.timeout = config.ollama.timeout
        self.temperature = config.ollama.temperature

        self._client = httpx.AsyncClient(timeout=self.timeout)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "ollama"

    async def is_available(self) -> bool:
        """Check if Ollama is running"""
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List available models"""
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
        return []

    async def pull_model(self, model: str) -> bool:
        """Pull a model from Ollama registry"""
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"name": model},
                timeout=600,  # 10 minutes for pull
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if data.get("status") == "success":
                            return True
        except Exception as e:
            logger.error(f"Failed to pull model: {e}")
        return False

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
        Generate a chat completion via Ollama

        Args:
            messages: List of messages in the conversation
            tools: List of available tools (function schemas)
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate

        Returns:
            Tuple of (response_text, tool_calls)
        """
        # Convert messages to Ollama format
        ollama_messages = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature or self.temperature,
                "num_predict": max_tokens,
            },
        }

        # Add tools if supported
        if tools:
            payload["tools"] = self._convert_tools(tools)

        try:
            response = await self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            message = data.get("message", {})

            text = message.get("content", "")
            tool_calls = self._parse_tool_calls(message.get("tool_calls", []))

            return text, tool_calls

        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            raise

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """
        Generate a streaming chat completion via Ollama

        Yields chunks of the response text
        """
        ollama_messages = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "temperature": temperature or self.temperature,
                "num_predict": max_tokens,
            },
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if "message" in data:
                            content = data["message"].get("content", "")
                            if content:
                                yield content
        except Exception as e:
            logger.error(f"Ollama streaming failed: {e}")
            raise

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert Quokka messages to Ollama format"""
        result = []
        for msg in messages:
            ollama_msg: dict[str, Any] = {"role": msg.role.value}

            # Handle content
            if msg.images:
                # Multimodal message with images
                ollama_msg["content"] = msg.content
                ollama_msg["images"] = msg.images  # Base64 encoded
            else:
                ollama_msg["content"] = msg.content

            # Handle tool calls
            if msg.tool_calls:
                ollama_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]

            result.append(ollama_msg)

            # Handle tool results (as separate messages)
            for tr in msg.tool_results:
                result.append({
                    "role": "tool",
                    "content": json.dumps(tr.output) if isinstance(tr.output, dict) else str(tr.output),
                    "name": tr.tool_name,
                })

        return result

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tool schemas to Ollama format"""
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
        """Parse Ollama tool calls to ToolCall objects"""
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
