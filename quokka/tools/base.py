"""
Base tool interface and registry
"""

from __future__ import annotations

import asyncio
import subprocess
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from ..core.types import ToolResult


class ToolSchema(BaseModel):
    """JSON schema for a tool"""

    name: str
    description: str
    parameters: dict[str, Any]


class BaseTool(ABC):
    """
    Abstract base class for all tools

    Tools are the actions the agent can perform.
    Each tool must implement execute() and provide its schema.
    """

    # Tool metadata (override in subclasses)
    name: ClassVar[str] = "base_tool"
    description: ClassVar[str] = "Base tool class"
    parameters_schema: ClassVar[dict[str, Any]] = {}

    # Default settings
    timeout: int = 60
    requires_confirmation: bool = False

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool

        Args:
            **kwargs: Tool arguments

        Returns:
            ToolResult with execution result
        """
        pass

    @classmethod
    def get_schema(cls) -> ToolSchema:
        """Get the tool's JSON schema for LLM"""
        return ToolSchema(
            name=cls.name,
            description=cls.description,
            parameters=cls.parameters_schema,
        )

    @classmethod
    def to_openai_schema(cls) -> dict[str, Any]:
        """Convert to OpenAI function calling schema"""
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": cls.parameters_schema,
        }

    def validate_arguments(self, **kwargs: Any) -> dict[str, Any]:
        """
        Validate and normalize arguments

        Override to add custom validation logic
        """
        return kwargs


class ToolRegistry:
    """
    Registry for all available tools

    Manages tool registration, lookup, and schema generation
    """

    def __init__(self) -> None:
        """Initialize the tool registry"""
        self._tools: dict[str, type[BaseTool]] = {}

    def register(self, tool_class: type[BaseTool]) -> None:
        """Register a tool class"""
        self._tools[tool_class.name] = tool_class

    def get(self, name: str) -> type[BaseTool] | None:
        """Get a tool class by name"""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered"""
        return name in self._tools

    def list_tools(self) -> list[str]:
        """List all registered tool names"""
        return list(self._tools.keys())

    def get_schemas(self) -> list[ToolSchema]:
        """Get schemas for all tools"""
        return [tool.get_schema() for tool in self._tools.values()]

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI-compatible schemas for all tools"""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def create_instance(self, name: str) -> BaseTool | None:
        """Create an instance of a tool"""
        tool_class = self.get(name)
        if tool_class:
            return tool_class()
        return None


def run_subprocess(
    command: str,
    timeout: int = 60,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """
    Helper to run a subprocess synchronously

    Args:
        command: Command to run
        timeout: Timeout in seconds
        cwd: Working directory
        env: Environment variables

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ, **(env or {})},
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout} seconds"
    except Exception as e:
        return -1, "", str(e)


async def run_subprocess_async(
    command: str,
    timeout: int = 60,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """
    Helper to run a subprocess asynchronously

    Args:
        command: Command to run
        timeout: Timeout in seconds
        cwd: Working directory
        env: Environment variables

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, **(env or {})},
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
            return (
                process.returncode or 0,
                stdout.decode() if stdout else "",
                stderr.decode() if stderr else "",
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return -1, "", f"Command timed out after {timeout} seconds"

    except Exception as e:
        return -1, "", str(e)


# Import os for environment handling
import os
