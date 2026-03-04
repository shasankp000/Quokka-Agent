"""
Quokka Agent - Main agent class that coordinates all components
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .core.config import Config, get_config
from .core.logger import get_logger, setup_logging
from .core.types import Message, MessageType, Plan, ToolCall, ToolResult
from .executor.executor import ExecutionContext, ToolExecutor
from .llm.router import LLMRouter
from .memory.session import SessionManager
from .memory.task_queue import TaskQueue
from .multimodal.handler import MultimodalHandler
from .planner.planner import Planner
from .security.security import SecurityLayer
from .tools.base import ToolRegistry
from .tools.shell_exec import ShellExecTool, ShellBackgroundTool
from .tools.file_ops import FileOpsTool
from .tools.pdf_handler import PDFHandlerTool
from .tools.web_fetch import WebFetchTool
from .tools.obsidian import ObsidianReadTool, ObsidianWriteTool

logger = get_logger(__name__)


class QuokkaAgent:
    """
    Main Quokka Agent class

    Coordinates all components:
    - Transport (Telegram)
    - LLM (Ollama/OpenRouter)
    - Security
    - Tools
    - Memory
    - Multimodal
    """

    def __init__(self, config: Config | None = None) -> None:
        """
        Initialize the Quokka Agent

        Args:
            config: Configuration (defaults to global config)
        """
        self.config = config or get_config()

        # Setup logging
        setup_logging(
            level=self.config.logging.level,
            log_file=self.config.logging.file,
            max_size_mb=self.config.logging.max_size_mb,
            backup_count=self.config.logging.backup_count,
        )

        logger.info("Initializing Quokka Agent...")

        # Initialize components
        self._init_tools()
        self._init_security()
        self._init_llm()
        self._init_memory()
        self._init_executor()
        self._init_planner()
        self._init_multimodal()

        # Transport will be set later
        self._telegram = None

        logger.info("Quokka Agent initialized successfully")

    def _init_tools(self) -> None:
        """Initialize tool registry"""
        self.tools = ToolRegistry()

        # Register all tools
        self.tools.register(ShellExecTool)
        self.tools.register(ShellBackgroundTool)
        self.tools.register(FileOpsTool)
        self.tools.register(PDFHandlerTool)
        self.tools.register(WebFetchTool)
        self.tools.register(ObsidianReadTool)
        self.tools.register(ObsidianWriteTool)

        logger.info(f"Registered {len(self.tools.list_tools())} tools")

    def _init_security(self) -> None:
        """Initialize security layer"""
        self.security = SecurityLayer()
        logger.info("Security layer initialized")

    def _init_llm(self) -> None:
        """Initialize LLM router"""
        self.llm = LLMRouter()
        logger.info("LLM router initialized")

    def _init_memory(self) -> None:
        """Initialize memory components"""
        self.sessions = SessionManager()
        self.task_queue = TaskQueue()
        logger.info("Memory components initialized")

    def _init_executor(self) -> None:
        """Initialize tool executor"""
        self.executor = ToolExecutor(self.tools, self.security)

        # Set completion callback
        async def on_complete(tc: ToolCall, result: ToolResult) -> None:
            logger.debug(f"Tool completed: {tc.name}")

        self.executor.set_completion_callback(on_complete)
        logger.info("Tool executor initialized")

    def _init_planner(self) -> None:
        """Initialize planner"""
        self.planner = Planner()
        logger.info("Planner initialized")

    def _init_multimodal(self) -> None:
        """Initialize multimodal handler"""
        self.multimodal = MultimodalHandler()
        logger.info("Multimodal handler initialized")

    def set_telegram(self, telegram: Any) -> None:
        """Set the Telegram bot instance"""
        self._telegram = telegram

    async def process_message(self, message: Message, user_id: int) -> Message:
        """
        Process an incoming message

        This is the main entry point for handling user messages.

        Args:
            message: The incoming message
            user_id: User ID

        Returns:
            Response message
        """
        logger.info(f"Processing message from user {user_id}: {message.content[:100]}...")

        try:
            # Get or create session
            chat_id = message.metadata.get("chat_id", user_id)
            session = await self.sessions.get_or_create(user_id, chat_id)

            # Process multimodal content
            message = await self.multimodal.process_message(message)

            # Add to session
            await self.sessions.add_message(session, message)

            # Set user context for security
            is_admin = user_id in self.config.telegram.admin_users
            self.security.set_user_context(user_id, is_admin)

            # Get context for LLM
            context_messages = await self.sessions.get_context(session)

            # Get tool schemas
            tool_schemas = self.tools.get_openai_schemas()

            # Call LLM
            response_text, tool_calls, provider = await self.llm.chat(
                messages=context_messages,
                tools=tool_schemas,
            )

            logger.debug(f"LLM response from {provider}: {response_text[:100]}...")

            # If there are tool calls, execute them
            if tool_calls:
                return await self._handle_tool_calls(
                    tool_calls, session, user_id, is_admin, response_text
                )

            # No tool calls - return response directly
            response_message = Message(
                role=MessageType.ASSISTANT,
                content=response_text,
            )

            await self.sessions.add_message(session, response_message)
            return response_message

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            return Message(
                role=MessageType.ERROR,
                content=f"❌ Error: {str(e)}",
            )

    async def _handle_tool_calls(
        self,
        tool_calls: list[ToolCall],
        session: Any,
        user_id: int,
        is_admin: bool,
        initial_response: str,
    ) -> Message:
        """
        Handle tool calls from LLM

        Args:
            tool_calls: List of tool calls to execute
            session: Current session
            user_id: User ID
            is_admin: Whether user is admin
            initial_response: LLM's initial response text

        Returns:
            Response message with results
        """
        # Create execution context
        context = ExecutionContext(
            session_id=session.id,
            user_id=user_id,
            is_admin=is_admin,
            dry_run=session.dry_run_mode,
        )

        # Execute tools
        results: list[ToolResult] = []

        for tool_call in tool_calls:
            # Check if confirmation is needed
            needs_confirm = self.executor.needs_confirmation(tool_call, context)

            if needs_confirm and self._telegram:
                # Request confirmation via Telegram
                confirmed = await self._request_confirmation(tool_call, session)

                if not confirmed:
                    results.append(ToolResult(
                        call_id=tool_call.id,
                        tool_name=tool_call.name,
                        success=False,
                        error="User rejected the action",
                    ))
                    continue

            # Execute the tool
            result = await self.executor.execute(tool_call, context)
            results.append(result)

            # Stop on failure
            if not result.success:
                logger.warning(f"Tool {tool_call.name} failed, stopping execution")
                break

        # Format results for LLM
        results_summary = self._format_results(results)

        # Get follow-up response from LLM
        result_message = Message(
            role=MessageType.TOOL,
            content=results_summary,
            tool_results=results,
        )

        await self.sessions.add_message(session, result_message)

        # Get LLM's interpretation of results
        context_messages = await self.sessions.get_context(session)

        follow_up_text, follow_up_calls, _ = await self.llm.chat(
            messages=context_messages,
            tools=self.tools.get_openai_schemas(),
        )

        # If more tool calls, handle them recursively
        if follow_up_calls:
            return await self._handle_tool_calls(
                follow_up_calls, session, user_id, is_admin, follow_up_text
            )

        # Return final response
        response_message = Message(
            role=MessageType.ASSISTANT,
            content=follow_up_text,
            tool_results=results,
        )

        await self.sessions.add_message(session, response_message)
        return response_message

    async def _request_confirmation(self, tool_call: ToolCall, session: Any) -> bool:
        """
        Request user confirmation for a tool call

        Args:
            tool_call: Tool call to confirm
            session: Current session

        Returns:
            True if confirmed, False otherwise
        """
        if not self._telegram:
            # No Telegram, auto-approve
            return True

        # Create a future for the confirmation
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()

        async def on_confirm(approved: bool) -> None:
            future.set_result(approved)

        # Register callback
        self._telegram.register_confirmation_callback(tool_call.id, on_confirm)

        # Send confirmation request
        chat_id = session.chat_id if hasattr(session, 'chat_id') else session.user_id
        await self._telegram._send_confirmation(chat_id, tool_call)

        # Wait for response (with timeout)
        try:
            return await asyncio.wait_for(future, timeout=300)  # 5 min timeout
        except asyncio.TimeoutError:
            logger.warning(f"Confirmation timeout for {tool_call.id}")
            return False

    def _format_results(self, results: list[ToolResult]) -> str:
        """Format tool results for LLM context"""
        parts = ["Tool execution results:"]

        for result in results:
            status = "✅ SUCCESS" if result.success else "❌ FAILED"
            parts.append(f"\n{status}: {result.tool_name}")

            if result.output:
                output = str(result.output)[:1000]
                if len(str(result.output)) > 1000:
                    output += "..."
                parts.append(f"Output: {output}")

            if result.error:
                parts.append(f"Error: {result.error}")

        return "\n".join(parts)

    async def start(self) -> None:
        """Start the agent"""
        logger.info("Starting Quokka Agent...")

        # Check LLM availability
        if not await self.llm.is_available():
            raise RuntimeError("No LLM provider available. Check Ollama or OpenRouter configuration.")

        logger.info("Quokka Agent started successfully")

    async def stop(self) -> None:
        """Stop the agent"""
        logger.info("Stopping Quokka Agent...")

        # Close LLM connections
        await self.llm.close()

        logger.info("Quokka Agent stopped")
