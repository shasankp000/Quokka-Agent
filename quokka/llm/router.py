"""
LLM Router - Routes requests between local (Ollama) and cloud (OpenRouter)
"""

from __future__ import annotations

import re
from typing import Any

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import Message, ToolCall
from .base import BaseLLM
from .ollama_client import OllamaLLM
from .openrouter_client import OpenRouterLLM

logger = get_logger(__name__)


class LLMRouter:
    """
    Routes LLM requests between local and cloud providers

    Routing strategy:
    1. Always use local for simple tasks and specific tools
    2. Use cloud for complex reasoning, code review, etc.
    3. Fallback to cloud if local is unavailable
    4. Estimate complexity and compare against threshold
    """

    def __init__(self) -> None:
        """Initialize the router with both LLM clients"""
        self.config = get_config()
        self.local_llm = OllamaLLM()
        self.cloud_llm = OpenRouterLLM()

        # Patterns indicating complex tasks
        self._complex_patterns = [
            r'\b(analyze|analysis|compare|contrast|evaluate|assess)\b',
            r'\b(review|critique|feedback)\b',
            r'\b(complex|complicated|sophisticated)\b',
            r'\b(architecture|design|system)\b',
            r'\b(refactor|restructure|optimize)\b',
            r'\b(debug|troubleshoot|investigate)\b',
            r'\b(write|create|generate).*(essay|article|report|document)\b',
            r'\b(explain|describe).*(detailed|comprehensive|thorough)\b',
        ]

        self._simple_patterns = [
            r'\b(list|show|display|get|fetch)\b',
            r'\b(read|write|edit|update)\b.+\b(file|note)\b',
            r'\b(run|execute)\b.+\b(command|script)\b',
            r'\b(what|who|when|where)\b.+\b\?$',
        ]

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        prefer_local: bool = False,
        prefer_cloud: bool = False,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> tuple[str, list[ToolCall], str]:
        """
        Route chat request to appropriate LLM

        Args:
            messages: List of messages in the conversation
            tools: List of available tools
            prefer_local: Force use of local LLM
            prefer_cloud: Force use of cloud LLM
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate

        Returns:
            Tuple of (response_text, tool_calls, provider_used)
        """
        # Determine which provider to use
        provider = self._route(messages, tools, prefer_local, prefer_cloud)

        logger.info(f"Routing to {provider}")

        # Get the appropriate client
        if provider == "local":
            try:
                if not await self.local_llm.is_available():
                    logger.warning("Local LLM unavailable, falling back to cloud")
                    provider = "cloud"
                else:
                    text, tool_calls = await self.local_llm.chat(
                        messages, tools, temperature, max_tokens
                    )
                    return text, tool_calls, "local"
            except Exception as e:
                logger.error(f"Local LLM failed: {e}, falling back to cloud")
                provider = "cloud"

        if provider == "cloud":
            if not self.config.openrouter.api_key:
                raise ValueError("OpenRouter API key not configured and local LLM unavailable")

            text, tool_calls = await self.cloud_llm.chat(
                messages, tools, temperature, max_tokens
            )
            return text, tool_calls, "cloud"

        # This shouldn't happen, but just in case
        raise RuntimeError("No LLM provider available")

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        prefer_local: bool = False,
        prefer_cloud: bool = False,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ):
        """
        Route streaming chat request to appropriate LLM

        Yields tuples of (chunk, provider_used)
        """
        provider = self._route(messages, tools, prefer_local, prefer_cloud)
        logger.info(f"Routing stream to {provider}")

        if provider == "local":
            try:
                if not await self.local_llm.is_available():
                    logger.warning("Local LLM unavailable, falling back to cloud")
                    provider = "cloud"
                else:
                    async for chunk in self.local_llm.chat_stream(
                        messages, tools, temperature, max_tokens
                    ):
                        yield chunk, "local"
                    return
            except Exception as e:
                logger.error(f"Local LLM streaming failed: {e}, falling back to cloud")
                provider = "cloud"

        if provider == "cloud":
            if not self.config.openrouter.api_key:
                raise ValueError("OpenRouter API key not configured and local LLM unavailable")

            async for chunk in self.cloud_llm.chat_stream(
                messages, tools, temperature, max_tokens
            ):
                yield chunk, "cloud"
            return

        raise RuntimeError("No LLM provider available")

    def _route(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        prefer_local: bool,
        prefer_cloud: bool,
    ) -> str:
        """
        Determine which provider to use

        Returns:
            "local" or "cloud"
        """
        # Explicit preferences
        if prefer_local:
            return "local"
        if prefer_cloud:
            return "cloud"

        # Check last user message for routing hints
        last_user_msg = None
        for msg in reversed(messages):
            if msg.role.value == "user":
                last_user_msg = msg.content
                break

        if not last_user_msg:
            return "local"  # Default to local

        # Check for always-local tools
        if tools:
            tool_names = [t.get("name", "") for t in tools]
            for local_tool in self.config.router.always_local_tools:
                if local_tool in tool_names:
                    return "local"

        # Check complexity patterns
        content_lower = last_user_msg.lower()

        # Check for complex patterns
        for pattern in self.config.router.always_cloud_patterns:
            if pattern.lower() in content_lower:
                return "cloud"

        for pattern in self._complex_patterns:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return "cloud"

        # Check for simple patterns
        for pattern in self._simple_patterns:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return "local"

        # Estimate complexity
        complexity = self._estimate_complexity(last_user_msg, messages)
        threshold = self.config.router.complexity_threshold

        logger.debug(f"Estimated complexity: {complexity:.2f}, threshold: {threshold}")

        return "cloud" if complexity > threshold else "local"

    def _estimate_complexity(self, query: str, history: list[Message]) -> float:
        """
        Estimate task complexity on a scale of 0-1

        Factors:
        - Query length
        - Number of questions/tasks
        - Presence of code blocks
        - Conversation history length
        - Specific complexity indicators
        """
        score = 0.0

        # Length factor (longer = more complex)
        length_factor = min(len(query) / 500, 0.3)
        score += length_factor

        # Multiple questions/tasks
        question_count = query.count("?") + query.count(";")
        task_factor = min(question_count * 0.1, 0.2)
        score += task_factor

        # Code presence
        if "```" in query or "def " in query or "class " in query:
            score += 0.2

        # History length (more context = potentially more complex)
        history_factor = min(len(history) * 0.02, 0.15)
        score += history_factor

        # Negation/conditional logic
        conditionals = len(re.findall(r'\b(if|unless|except|but|however|although)\b', query, re.IGNORECASE))
        score += min(conditionals * 0.05, 0.15)

        return min(score, 1.0)

    async def is_available(self) -> bool:
        """Check if at least one LLM is available"""
        local = await self.local_llm.is_available()
        cloud = bool(self.config.openrouter.api_key)
        return local or cloud

    async def close(self) -> None:
        """Close all LLM clients"""
        await self.local_llm.close()
        await self.cloud_llm.close()
