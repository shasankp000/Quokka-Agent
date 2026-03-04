"""
Base LLM interface
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from ..core.types import Message, ToolCall


class BaseLLM(ABC):
    """Abstract base class for LLM providers"""

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple[str, list[ToolCall]]:
        """
        Generate a chat completion

        Args:
            messages: List of messages in the conversation
            tools: List of available tools (function schemas)
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate

        Returns:
            Tuple of (response_text, tool_calls)
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """
        Generate a streaming chat completion

        Args:
            messages: List of messages in the conversation
            tools: List of available tools (function schemas)
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate

        Yields:
            Chunks of the response text
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the LLM is available"""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the model name"""
        pass

    @property
    @abstractmethod
    def provider(self) -> str:
        """Get the provider name"""
        pass
