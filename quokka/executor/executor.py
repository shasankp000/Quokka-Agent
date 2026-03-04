"""
Tool Executor - Executes tools with isolation and monitoring
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import ToolCall, ToolResult
from ..security.security import SecurityLayer
from ..tools.base import BaseTool, ToolRegistry

logger = get_logger(__name__)


@dataclass
class ExecutionContext:
    """Context for tool execution"""

    session_id: str
    user_id: int | str
    is_admin: bool = False
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor:
    """
    Executes tools with security checks and monitoring

    Features:
    - Security validation before execution
    - Timeout management
    - Concurrent execution limits
    - Output capture and logging
    """

    def __init__(self, tool_registry: ToolRegistry, security: SecurityLayer) -> None:
        """
        Initialize the tool executor

        Args:
            tool_registry: Registry of available tools
            security: Security layer for validation
        """
        self.registry = tool_registry
        self.security = security
        self.config = get_config()

        # Execution limits
        self._max_concurrent = self.config.executor.max_concurrent_tasks
        self._default_timeout = self.config.executor.default_timeout
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        # Active executions
        self._active: dict[str, asyncio.Task[ToolResult]] = {}

        # Callbacks
        self._on_complete: Callable[[ToolCall, ToolResult], Coroutine[None, None, None]] | None = None

    def set_completion_callback(
        self, callback: Callable[[ToolCall, ToolResult], Coroutine[None, None, None]]
    ) -> None:
        """Set callback for when a tool execution completes"""
        self._on_complete = callback

    async def execute(
        self,
        tool_call: ToolCall,
        context: ExecutionContext,
    ) -> ToolResult:
        """
        Execute a tool call

        Args:
            tool_call: The tool call to execute
            context: Execution context with user info

        Returns:
            ToolResult with execution outcome
        """
        async with self._semaphore:
            return await self._execute_internal(tool_call, context)

    async def _execute_internal(
        self,
        tool_call: ToolCall,
        context: ExecutionContext,
    ) -> ToolResult:
        """Internal execution logic"""
        start_time = datetime.now()
        tool_name = tool_call.name
        args = tool_call.arguments

        logger.info(f"Executing tool: {tool_name} with args: {args}")

        # Set user context for security
        self.security.set_user_context(context.user_id, context.is_admin)

        # Security check
        security_decision = self.security.check_tool_call(tool_call, context.session_id)

        if not security_decision.allowed:
            logger.warning(f"Tool call blocked by security: {security_decision.reason}")
            return ToolResult(
                call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=f"Security: {security_decision.reason}",
            )

        # Dry-run mode
        if context.dry_run:
            logger.info(f"Dry-run mode: simulating {tool_name}")
            return ToolResult(
                call_id=tool_call.id,
                tool_name=tool_name,
                success=True,
                output=f"[DRY RUN] Would execute: {tool_name}({args})",
            )

        # Get tool instance
        tool_instance = self.registry.create_instance(tool_name)

        if not tool_instance:
            logger.error(f"Unknown tool: {tool_name}")
            return ToolResult(
                call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        # Execute with timeout
        timeout = self.security.validate_timeout(args.get("timeout", self._default_timeout))

        try:
            # Merge security-modified arguments if any
            if security_decision.modified_arguments:
                args = {**args, **security_decision.modified_arguments}

            # Create the execution task
            result = await asyncio.wait_for(
                tool_instance.execute(**args),
                timeout=timeout,
            )

            # Ensure result has correct call_id
            result.call_id = tool_call.id

            # Log execution
            self.security.log_execution(
                tool_name=tool_name,
                arguments=args,
                success=result.success,
                output=str(result.output)[:500] if result.output else None,
                error=result.error,
                session_id=context.session_id,
            )

            # Mark complete
            result.mark_complete()

            logger.info(f"Tool execution complete: {tool_name} (success={result.success})")

            # Call completion callback
            if self._on_complete:
                await self._on_complete(tool_call, result)

            return result

        except asyncio.TimeoutError:
            error_msg = f"Tool execution timed out after {timeout} seconds"
            logger.warning(error_msg)

            self.security.log_execution(
                tool_name=tool_name,
                arguments=args,
                success=False,
                error=error_msg,
                session_id=context.session_id,
            )

            return ToolResult(
                call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=error_msg,
            )

        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            logger.exception(error_msg)

            self.security.log_execution(
                tool_name=tool_name,
                arguments=args,
                success=False,
                error=error_msg,
                session_id=context.session_id,
            )

            return ToolResult(
                call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=error_msg,
            )

    async def execute_batch(
        self,
        tool_calls: list[ToolCall],
        context: ExecutionContext,
        stop_on_failure: bool = True,
    ) -> list[ToolResult]:
        """
        Execute multiple tool calls

        Args:
            tool_calls: List of tool calls to execute
            context: Execution context
            stop_on_failure: Whether to stop on first failure

        Returns:
            List of tool results
        """
        results = []

        for tool_call in tool_calls:
            result = await self.execute(tool_call, context)
            results.append(result)

            if stop_on_failure and not result.success:
                logger.warning(f"Batch execution stopped due to failure: {tool_call.name}")
                break

        return results

    async def execute_parallel(
        self,
        tool_calls: list[ToolCall],
        context: ExecutionContext,
    ) -> list[ToolResult]:
        """
        Execute multiple tool calls in parallel

        Args:
            tool_calls: List of tool calls to execute
            context: Execution context

        Returns:
            List of tool results (in same order as input)
        """
        tasks = [self.execute(tc, context) for tc in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error results
        final_results = []
        for tc, result in zip(tool_calls, results):
            if isinstance(result, Exception):
                final_results.append(ToolResult(
                    call_id=tc.id,
                    tool_name=tc.name,
                    success=False,
                    error=str(result),
                ))
            else:
                final_results.append(result)

        return final_results

    def needs_confirmation(self, tool_call: ToolCall, context: ExecutionContext) -> bool:
        """
        Check if a tool call needs user confirmation

        Args:
            tool_call: The tool call to check
            context: Execution context

        Returns:
            True if confirmation is needed
        """
        # Admins bypass confirmation
        if context.is_admin:
            return False

        # Check security layer
        if self.security.should_confirm(tool_call):
            return True

        # Check tool default
        tool_class = self.registry.get(tool_call.name)
        if tool_class and tool_class.requires_confirmation:
            return True

        return False

    def get_active_count(self) -> int:
        """Get number of active executions"""
        return len([t for t in self._active.values() if not t.done()])

    def cancel_all(self) -> int:
        """Cancel all active executions"""
        count = 0
        for task in self._active.values():
            if not task.done():
                task.cancel()
                count += 1
        return count
