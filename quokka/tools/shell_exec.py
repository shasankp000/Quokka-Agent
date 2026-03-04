"""
Shell execution tool
"""

from __future__ import annotations

import os
from typing import Any, ClassVar

from ..core.types import ToolResult
from ..core.logger import get_logger
from .base import BaseTool, run_subprocess_async

logger = get_logger(__name__)


class ShellExecTool(BaseTool):
    """
    Execute shell commands

    Security: Commands are validated against allowlist/blocklist
    by the security layer before execution.
    """

    name: ClassVar[str] = "shell_exec"
    description: ClassVar[str] = (
        "Execute a shell command on the system. "
        "Use with caution - commands are restricted by security policy. "
        "Returns the command output and exit code."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 60, max: 300)",
                "default": 60,
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the command",
            },
        },
        "required": ["command"],
    }

    timeout: int = 60
    requires_confirmation: bool = True  # Shell commands need confirmation

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute a shell command

        Args:
            command: The command to run
            timeout: Timeout in seconds
            cwd: Working directory

        Returns:
            ToolResult with stdout/stderr and exit code
        """
        command = kwargs.get("command", "")
        timeout = min(kwargs.get("timeout", 60), 300)  # Max 5 minutes
        cwd = kwargs.get("cwd")

        if not command:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No command provided",
            )

        logger.info(f"Executing command: {command}")

        # Execute the command
        returncode, stdout, stderr = await run_subprocess_async(
            command=command,
            timeout=timeout,
            cwd=cwd,
        )

        # Prepare output
        output_parts = []
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        output_parts.append(f"Exit code: {returncode}")

        output = "\n\n".join(output_parts)

        # Truncate very long output
        if len(output) > 10000:
            output = output[:10000] + "\n\n... [output truncated]"

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=returncode == 0,
            output=output,
            error=stderr if returncode != 0 else None,
        )


class ShellBackgroundTool(BaseTool):
    """
    Execute a shell command in the background

    Useful for long-running tasks that don't need immediate output.
    """

    name: ClassVar[str] = "shell_background"
    description: ClassVar[str] = (
        "Execute a shell command in the background. "
        "Returns immediately with a process ID. "
        "Use for long-running tasks like servers or watchers."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute in background",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the command",
            },
        },
        "required": ["command"],
    }

    requires_confirmation: bool = True

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute a command in background

        Args:
            command: The command to run
            cwd: Working directory

        Returns:
            ToolResult with process ID
        """
        command = kwargs.get("command", "")
        cwd = kwargs.get("cwd")

        if not command:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No command provided",
            )

        logger.info(f"Starting background command: {command}")

        import asyncio

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
            start_new_session=True,  # Detach from parent
        )

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Started background process with PID: {process.pid}",
        )
