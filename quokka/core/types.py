"""
Core types and models for the Quokka Agent
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class MessageType(str, Enum):
    """Types of messages in a conversation"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    ERROR = "error"


class TaskStatus(str, Enum):
    """Status of a task in the queue"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_CONFIRMATION = "waiting_confirmation"


class ToolCall(BaseModel):
    """Represents a tool call to be executed"""

    id: str = Field(default_factory=lambda: f"call_{uuid4().hex[:8]}")
    name: str = Field(description="Name of the tool to call")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")
    order: int = Field(default=0, description="Execution order in the plan")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    requires_confirmation: bool = Field(default=False, description="Whether this requires user confirmation")

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "ToolCall":
        return cls.model_validate_json(json_str)


class ToolResult(BaseModel):
    """Result of a tool execution"""

    call_id: str = Field(description="ID of the tool call this result is for")
    tool_name: str = Field(description="Name of the tool that was executed")
    success: bool = Field(description="Whether the execution was successful")
    output: str | dict[str, Any] | None = Field(default=None, description="Output from the tool")
    error: str | None = Field(default=None, description="Error message if failed")

    # Metadata
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = Field(default=None)
    duration_seconds: float | None = Field(default=None)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "ToolResult":
        return cls.model_validate_json(json_str)

    def mark_complete(self) -> None:
        """Mark the result as complete"""
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()


class Message(BaseModel):
    """A message in the conversation"""

    id: str = Field(default_factory=lambda: f"msg_{uuid4().hex[:8]}")
    role: MessageType = Field(description="Role of the message sender")
    content: str = Field(default="", description="Text content of the message")

    # Tool-related fields
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Tool calls in this message")
    tool_results: list[ToolResult] = Field(default_factory=list, description="Tool results in this message")

    # Multimodal content
    attachments: list[str] = Field(default_factory=list, description="Paths to attached files")
    images: list[str] = Field(default_factory=list, description="Base64 encoded images or URLs")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible message format"""
        msg: dict[str, Any] = {"role": self.role.value}

        if self.content:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]

        if self.tool_results:
            # Tool results are separate messages in OpenAI format
            # This should be handled by the caller
            pass

        if self.images:
            # Convert to multimodal content
            content = [{"type": "text", "text": self.content}] if self.content else []
            for img in self.images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img if img.startswith("http") else f"data:image/jpeg;base64,{img}"},
                })
            msg["content"] = content

        return msg

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        return cls.model_validate_json(json_str)


class Session(BaseModel):
    """A conversation session"""

    id: str = Field(default_factory=lambda: f"sess_{uuid4().hex[:8]}")
    user_id: int | str = Field(description="Telegram user ID or identifier")
    chat_id: int | str = Field(description="Telegram chat ID or identifier")

    # Conversation
    messages: list[Message] = Field(default_factory=list, description="Messages in this session")

    # State
    dry_run_mode: bool = Field(default=False, description="Whether dry-run mode is active")
    active_tool_calls: list[ToolCall] = Field(default_factory=list, description="Tool calls awaiting execution")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_message(self, message: Message) -> None:
        """Add a message to the session"""
        self.messages.append(message)
        self.updated_at = datetime.now()

    def get_context_window(self, max_messages: int = 50) -> list[Message]:
        """Get the most recent messages for context"""
        return self.messages[-max_messages:]

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "Session":
        return cls.model_validate_json(json_str)

    def save(self, directory: Path) -> Path:
        """Save session to file"""
        directory.mkdir(parents=True, exist_ok=True)
        filepath = directory / f"{self.id}.json"
        filepath.write_text(self.to_json())
        return filepath

    @classmethod
    def load(cls, filepath: Path) -> "Session":
        """Load session from file"""
        return cls.from_json(filepath.read_text())


class Task(BaseModel):
    """A task in the async task queue"""

    id: str = Field(default_factory=lambda: f"task_{uuid4().hex[:8]}")
    user_id: int | str = Field(description="User who created the task")

    # Task definition
    description: str = Field(description="Human-readable description")
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Planned tool calls")

    # Status
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    progress: float = Field(default=0.0, description="Progress percentage (0-100)")
    result: str | None = Field(default=None, description="Final result or error message")

    # Scheduling
    scheduled_at: datetime | None = Field(default=None, description="When to execute (None = immediate)")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "Task":
        return cls.model_validate_json(json_str)


class Plan(BaseModel):
    """A plan formulated by the LLM"""

    id: str = Field(default_factory=lambda: f"plan_{uuid4().hex[:8]}")
    original_request: str = Field(description="The original user request")
    reasoning: str = Field(default="", description="LLM's reasoning for the plan")

    # Ordered tool calls
    tool_calls: list[ToolCall] = Field(default_factory=list, description="Ordered list of tool calls")

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    complexity_score: float = Field(default=0.5, description="Estimated complexity (0-1)")
    requires_confirmation: bool = Field(default=False, description="Whether plan needs user confirmation")

    @field_validator("tool_calls")
    @classmethod
    def assign_order(cls, v: list[ToolCall]) -> list[ToolCall]:
        """Ensure tool calls have proper order"""
        for i, tc in enumerate(v):
            tc.order = i
        return v

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "Plan":
        return cls.model_validate_json(json_str)


class SecurityDecision(BaseModel):
    """Result of a security check"""

    allowed: bool = Field(description="Whether the action is allowed")
    reason: str = Field(default="", description="Reason for the decision")
    blocked_by: str | None = Field(default=None, description="Which security check blocked it")

    # Details
    modified_arguments: dict[str, Any] | None = Field(
        default=None, description="Modified arguments after sanitization"
    )
    warnings: list[str] = Field(default_factory=list, description="Warnings to show to user")

    # Audit info
    timestamp: datetime = Field(default_factory=datetime.now)
    severity: str = Field(default="info", description="Severity level: info, warning, error, critical")
