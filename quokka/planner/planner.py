"""
Planner and Tool Call Queue

Formulates execution plans from LLM responses and manages the queue
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import Message, MessageType, Plan, ToolCall, ToolResult

logger = get_logger(__name__)


class ToolCallQueue:
    """
    Ordered queue of tool calls to execute

    Manages:
    - Adding tool calls from plans
    - Tracking execution state
    - Handling dependencies between calls
    """

    def __init__(self) -> None:
        """Initialize the tool call queue"""
        self._queue: deque[ToolCall] = deque()
        self._completed: list[tuple[ToolCall, ToolResult]] = []
        self._pending_confirmation: dict[str, ToolCall] = {}

    def add(self, tool_calls: list[ToolCall]) -> None:
        """Add tool calls to the queue"""
        for tc in tool_calls:
            self._queue.append(tc)
            logger.debug(f"Queued tool call: {tc.name}")

    def add_from_plan(self, plan: Plan) -> None:
        """Add all tool calls from a plan"""
        self.add(plan.tool_calls)

    def get_next(self) -> ToolCall | None:
        """Get the next tool call to execute"""
        if self._queue:
            return self._queue.popleft()
        return None

    def peek(self) -> ToolCall | None:
        """Peek at the next tool call without removing it"""
        if self._queue:
            return self._queue[0]
        return None

    def mark_pending_confirmation(self, tool_call: ToolCall) -> None:
        """Mark a tool call as awaiting confirmation"""
        self._pending_confirmation[tool_call.id] = tool_call

    def confirm(self, call_id: str, approved: bool) -> ToolCall | None:
        """
        Confirm or reject a pending tool call

        Returns the tool call if approved, None otherwise
        """
        if call_id in self._pending_confirmation:
            tc = self._pending_confirmation.pop(call_id)
            if approved:
                return tc
        return None

    def complete(self, tool_call: ToolCall, result: ToolResult) -> None:
        """Mark a tool call as completed with its result"""
        self._completed.append((tool_call, result))
        logger.debug(f"Completed tool call: {tool_call.name}")

    def is_empty(self) -> bool:
        """Check if the queue is empty"""
        return len(self._queue) == 0 and len(self._pending_confirmation) == 0

    def has_pending(self) -> bool:
        """Check if there are pending confirmations"""
        return len(self._pending_confirmation) > 0

    def size(self) -> int:
        """Get the number of pending tool calls"""
        return len(self._queue)

    def clear(self) -> None:
        """Clear the queue"""
        self._queue.clear()
        self._pending_confirmation.clear()

    def get_completed_results(self) -> list[tuple[ToolCall, ToolResult]]:
        """Get all completed tool call results"""
        return self._completed.copy()

    def get_summary(self) -> str:
        """Get a summary of the queue state"""
        lines = [
            f"Tool Call Queue:",
            f"  Pending: {self.size()}",
            f"  Awaiting confirmation: {len(self._pending_confirmation)}",
            f"  Completed: {len(self._completed)}",
        ]

        if self._queue:
            lines.append("\n  Next up:")
            for i, tc in enumerate(list(self._queue)[:5]):
                lines.append(f"    {i + 1}. {tc.name}({json.dumps(tc.arguments)[:50]}...)")

        return "\n".join(lines)


class Planner:
    """
    Formulates execution plans from user requests

    Uses the LLM to:
    1. Understand the user's intent
    2. Break down complex requests into steps
    3. Select appropriate tools
    4. Order tool calls correctly
    """

    def __init__(self) -> None:
        """Initialize the planner"""
        self.config = get_config()
        self.queue = ToolCallQueue()
        self._current_plan: Plan | None = None

    def get_system_prompt(self, tools: list[dict[str, Any]]) -> str:
        """
        Generate the system prompt for the planner LLM

        Args:
            tools: List of available tool schemas

        Returns:
            System prompt string
        """
        tools_description = "\n".join([
            f"- {t['name']}: {t.get('description', 'No description')}"
            for t in tools
        ])

        return f"""You are Quokka, an intelligent automation agent. You help users by executing tools on their computer.

## Available Tools

{tools_description}

## Planning Guidelines

1. **Understand the Request**: Analyze what the user wants to accomplish
2. **Break Down**: Split complex requests into smaller, sequential steps
3. **Select Tools**: Choose the most appropriate tools for each step
4. **Order Matters**: Execute steps in the correct order (create directory before writing file, etc.)
5. **Be Efficient**: Combine operations when possible, avoid redundant steps

## Tool Call Format

When you need to use tools, output them in this JSON format:

```json
{{
  "reasoning": "Brief explanation of your plan",
  "tool_calls": [
    {{
      "name": "tool_name",
      "arguments": {{
        "arg1": "value1",
        "arg2": "value2"
      }}
    }}
  ]
}}
```

## Safety Considerations

- Always verify file paths before operations
- Use dry-run mode for dangerous operations
- Ask for clarification if the request is ambiguous
- Never execute commands that could cause data loss without confirmation

## Response Format

For each user message:
1. Think through the request (shown in reasoning)
2. If tools are needed, output the JSON plan
3. If no tools are needed, respond conversationally
4. If you need clarification, ask questions

Remember: You are running locally on the user's machine. Be helpful but careful.
"""

    def parse_llm_response(self, response: str, original_request: str) -> Plan | None:
        """
        Parse an LLM response to extract a plan

        Args:
            response: The LLM's response text
            original_request: The original user request

        Returns:
            Plan object if tool calls were found, None otherwise
        """
        # Look for JSON in the response
        json_patterns = [
            r'```json\s*(\{.*?\})\s*```',
            r'```\s*(\{.*?\})\s*```',
            r'(\{[\s\S]*"tool_calls"[\s\S]*\})',
        ]

        for pattern in json_patterns:
            import re
            match = re.search(pattern, response, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))

                    if "tool_calls" in data:
                        tool_calls = []
                        for i, tc_data in enumerate(data["tool_calls"]):
                            tool_calls.append(ToolCall(
                                id=f"call_{i}",
                                name=tc_data.get("name", ""),
                                arguments=tc_data.get("arguments", {}),
                                order=i,
                            ))

                        return Plan(
                            original_request=original_request,
                            reasoning=data.get("reasoning", ""),
                            tool_calls=tool_calls,
                        )

                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON from response: {e}")
                    continue

        return None

    def create_plan(
        self,
        tool_calls: list[ToolCall],
        original_request: str,
        reasoning: str = "",
    ) -> Plan:
        """
        Create a plan from a list of tool calls

        Args:
            tool_calls: List of tool calls
            original_request: Original user request
            reasoning: Reasoning for the plan

        Returns:
            Plan object
        """
        return Plan(
            original_request=original_request,
            reasoning=reasoning,
            tool_calls=tool_calls,
        )

    def queue_plan(self, plan: Plan) -> None:
        """Add a plan's tool calls to the execution queue"""
        self._current_plan = plan
        self.queue.add_from_plan(plan)

    def get_next_tool_call(self) -> ToolCall | None:
        """Get the next tool call from the queue"""
        return self.queue.get_next()

    def has_pending_work(self) -> bool:
        """Check if there's work in the queue"""
        return not self.queue.is_empty()

    def format_plan_for_display(self, plan: Plan) -> str:
        """Format a plan for display to the user"""
        lines = [
            "📋 **Execution Plan**",
            f"*{plan.reasoning}*" if plan.reasoning else "",
            "",
        ]

        for i, tc in enumerate(plan.tool_calls, 1):
            args_str = ", ".join(f"{k}={v}" for k, v in list(tc.arguments.items())[:3])
            if len(tc.arguments) > 3:
                args_str += "..."
            lines.append(f"{i}. `{tc.name}`({args_str})")

        return "\n".join(lines)

    def format_results_summary(self) -> str:
        """Format a summary of completed tool results"""
        completed = self.queue.get_completed_results()

        if not completed:
            return "No tool executions completed."

        lines = ["📊 **Execution Results**", ""]

        for tc, result in completed:
            status = "✅" if result.success else "❌"
            lines.append(f"{status} `{tc.name}`")

            if result.success:
                output = str(result.output)[:200]
                if len(str(result.output)) > 200:
                    output += "..."
                lines.append(f"   {output}")
            else:
                lines.append(f"   Error: {result.error}")

        return "\n".join(lines)
