"""
Task Queue - Persistent async task management
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import Task, TaskStatus, ToolCall

logger = get_logger(__name__)


class TaskQueue:
    """
    Persistent task queue for async operations

    Features:
    - Save tasks for later execution
    - Schedule tasks
    - Track task progress
    - Resume tasks after restart
    """

    def __init__(self, queue_file: Path | None = None) -> None:
        """
        Initialize the task queue

        Args:
            queue_file: Path to the queue file
        """
        self.config = get_config()
        self.queue_file = queue_file or self.config.memory.task_queue_file
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)

        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()

        # Load existing tasks
        self._load_tasks()

    def _load_tasks(self) -> None:
        """Load existing tasks from disk"""
        if not self.queue_file.exists():
            return

        try:
            with open(self.queue_file) as f:
                data = json.load(f)

            for task_data in data.get("tasks", []):
                task = Task.from_json(json.dumps(task_data))
                # Only load pending tasks
                if task.status == TaskStatus.PENDING:
                    self._tasks[task.id] = task

            logger.info(f"Loaded {len(self._tasks)} pending tasks")

        except Exception as e:
            logger.warning(f"Failed to load task queue: {e}")

    async def _save_tasks(self) -> None:
        """Save tasks to disk"""
        async with self._lock:
            data = {
                "tasks": [json.loads(task.to_json()) for task in self._tasks.values()],
                "updated_at": datetime.now().isoformat(),
            }

            with open(self.queue_file, "w") as f:
                json.dump(data, f, indent=2)

    async def add(
        self,
        description: str,
        tool_calls: list[ToolCall],
        user_id: int | str,
        scheduled_at: datetime | None = None,
    ) -> Task:
        """
        Add a new task to the queue

        Args:
            description: Human-readable description
            tool_calls: Tool calls to execute
            user_id: User who created the task
            scheduled_at: When to execute (None = immediate)

        Returns:
            Created task
        """
        task = Task(
            id=f"task_{uuid4().hex[:8]}",
            user_id=user_id,
            description=description,
            tool_calls=tool_calls,
            status=TaskStatus.PENDING,
            scheduled_at=scheduled_at,
        )

        async with self._lock:
            self._tasks[task.id] = task

        await self._save_tasks()

        logger.info(f"Added task {task.id}: {description}")

        return task

    async def get_next(self) -> Task | None:
        """
        Get the next task to execute

        Returns:
            Next pending task, or None if none available
        """
        async with self._lock:
            now = datetime.now()

            for task in sorted(self._tasks.values(), key=lambda t: t.created_at):
                if task.status == TaskStatus.PENDING:
                    # Check if scheduled time has passed
                    if task.scheduled_at is None or task.scheduled_at <= now:
                        task.status = TaskStatus.RUNNING
                        task.started_at = now
                        return task

        return None

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: str | None = None,
        progress: float | None = None,
    ) -> None:
        """
        Update a task's status

        Args:
            task_id: Task to update
            status: New status
            result: Result message
            progress: Progress percentage
        """
        async with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                task.status = status
                task.updated_at = datetime.now()

                if result is not None:
                    task.result = result

                if progress is not None:
                    task.progress = progress

                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    task.completed_at = datetime.now()

        await self._save_tasks()

    async def remove(self, task_id: str) -> bool:
        """
        Remove a task from the queue

        Args:
            task_id: Task to remove

        Returns:
            True if task was removed
        """
        async with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                await self._save_tasks()
                return True
        return False

    async def cancel(self, task_id: str) -> bool:
        """
        Cancel a pending task

        Args:
            task_id: Task to cancel

        Returns:
            True if task was cancelled
        """
        async with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                    task.updated_at = datetime.now()
                    await self._save_tasks()
                    return True
        return False

    def get_user_tasks(self, user_id: int | str) -> list[Task]:
        """
        Get all tasks for a user

        Args:
            user_id: User to get tasks for

        Returns:
            List of tasks
        """
        return [
            task for task in self._tasks.values()
            if task.user_id == user_id
        ]

    def get_pending_count(self) -> int:
        """Get number of pending tasks"""
        return sum(
            1 for task in self._tasks.values()
            if task.status == TaskStatus.PENDING
        )

    def get_running_count(self) -> int:
        """Get number of running tasks"""
        return sum(
            1 for task in self._tasks.values()
            if task.status == TaskStatus.RUNNING
        )

    async def clear_completed(self) -> int:
        """
        Remove completed/failed/cancelled tasks

        Returns:
            Number of tasks removed
        """
        count = 0
        async with self._lock:
            to_remove = [
                task_id for task_id, task in self._tasks.items()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]

            for task_id in to_remove:
                del self._tasks[task_id]
                count += 1

        if count:
            await self._save_tasks()
            logger.info(f"Cleared {count} completed tasks")

        return count

    def format_task_list(self, tasks: list[Task]) -> str:
        """Format a list of tasks for display"""
        if not tasks:
            return "No tasks."

        lines = ["📋 **Tasks**\n"]

        status_icons = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "🔄",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.CANCELLED: "🚫",
            TaskStatus.WAITING_CONFIRMATION: "⏸️",
        }

        for task in tasks:
            icon = status_icons.get(task.status, "❓")
            lines.append(f"{icon} **{task.id}**: {task.description}")

            if task.progress > 0:
                lines.append(f"   Progress: {task.progress:.0f}%")

            if task.result:
                result_preview = task.result[:100]
                if len(task.result) > 100:
                    result_preview += "..."
                lines.append(f"   Result: {result_preview}")

            lines.append("")

        return "\n".join(lines)
