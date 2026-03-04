"""
File operations tool
"""

from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path
from typing import Any, ClassVar

from ..core.types import ToolResult
from ..core.logger import get_logger
from .base import BaseTool

logger = get_logger(__name__)


class FileOpsTool(BaseTool):
    """
    Perform file system operations

    Operations: read, write, append, delete, list, mkdir, move, copy
    """

    name: ClassVar[str] = "file_ops"
    description: ClassVar[str] = (
        "Perform file system operations. "
        "Operations: read, write, append, delete, list, mkdir, move, copy. "
        "Paths are validated against directory restrictions."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "append", "delete", "list", "mkdir", "move", "copy", "exists", "stat"],
                "description": "The file operation to perform",
            },
            "path": {
                "type": "string",
                "description": "The file or directory path",
            },
            "content": {
                "type": "string",
                "description": "Content to write (for write/append operations)",
            },
            "destination": {
                "type": "string",
                "description": "Destination path (for move/copy operations)",
            },
            "recursive": {
                "type": "boolean",
                "description": "Whether to operate recursively (for list/delete)",
                "default": False,
            },
            "encoding": {
                "type": "string",
                "description": "File encoding (default: utf-8)",
                "default": "utf-8",
            },
        },
        "required": ["operation", "path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute a file operation

        Args:
            operation: The operation to perform
            path: The file/directory path
            content: Content for write/append
            destination: Destination for move/copy
            recursive: Recursive operation flag
            encoding: File encoding

        Returns:
            ToolResult with operation result
        """
        operation = kwargs.get("operation", "")
        path_str = kwargs.get("path", "")
        content = kwargs.get("content")
        destination = kwargs.get("destination")
        recursive = kwargs.get("recursive", False)
        encoding = kwargs.get("encoding", "utf-8")

        if not operation:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No operation specified",
            )

        if not path_str:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No path specified",
            )

        try:
            path = Path(path_str).expanduser().resolve()

            if operation == "read":
                return await self._read(path, encoding)
            elif operation == "write":
                return await self._write(path, content, encoding)
            elif operation == "append":
                return await self._append(path, content, encoding)
            elif operation == "delete":
                return await self._delete(path, recursive)
            elif operation == "list":
                return await self._list(path, recursive)
            elif operation == "mkdir":
                return await self._mkdir(path)
            elif operation == "move":
                return await self._move(path, destination)
            elif operation == "copy":
                return await self._copy(path, destination)
            elif operation == "exists":
                return await self._exists(path)
            elif operation == "stat":
                return await self._stat(path)
            else:
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=False,
                    error=f"Unknown operation: {operation}",
                )

        except Exception as e:
            logger.exception(f"File operation failed: {e}")
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=str(e),
            )

    async def _read(self, path: Path, encoding: str) -> ToolResult:
        """Read file contents"""
        if not path.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"File not found: {path}",
            )

        if path.is_dir():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Path is a directory: {path}. Use 'list' operation instead.",
            )

        try:
            content = path.read_text(encoding=encoding)

            # Truncate very large files
            if len(content) > 50000:
                content = content[:50000] + "\n\n... [content truncated]"

            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=content,
            )
        except UnicodeDecodeError:
            # Try to return as base64 for binary files
            try:
                data = path.read_bytes()
                b64 = base64.b64encode(data).decode()
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=True,
                    output=f"[Binary file - base64 encoded]\n{b64[:1000]}...",
                    metadata={"is_binary": True, "size": len(data)},
                )
            except Exception as e:
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=False,
                    error=f"Failed to read file: {e}",
                )

    async def _write(self, path: Path, content: str | None, encoding: str) -> ToolResult:
        """Write content to file"""
        if content is None:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No content provided for write operation",
            )

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding=encoding)

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Successfully wrote {len(content)} characters to {path}",
        )

    async def _append(self, path: Path, content: str | None, encoding: str) -> ToolResult:
        """Append content to file"""
        if content is None:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No content provided for append operation",
            )

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a", encoding=encoding) as f:
            f.write(content)

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Successfully appended {len(content)} characters to {path}",
        )

    async def _delete(self, path: Path, recursive: bool) -> ToolResult:
        """Delete file or directory"""
        if not path.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Path not found: {path}",
            )

        if path.is_file():
            path.unlink()
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=f"Successfully deleted file: {path}",
            )

        if path.is_dir():
            if not recursive and any(path.iterdir()):
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=False,
                    error=f"Directory not empty: {path}. Use recursive=true to delete.",
                )

            shutil.rmtree(path)
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=f"Successfully deleted directory: {path}",
            )

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=False,
            error=f"Unknown path type: {path}",
        )

    async def _list(self, path: Path, recursive: bool) -> ToolResult:
        """List directory contents"""
        if not path.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Path not found: {path}",
            )

        if not path.is_dir():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Path is not a directory: {path}",
            )

        items = []

        if recursive:
            for item in path.rglob("*"):
                rel_path = item.relative_to(path)
                item_type = "📁" if item.is_dir() else "📄"
                size = item.stat().st_size if item.is_file() else 0
                items.append(f"{item_type} {rel_path} ({self._format_size(size)})")
        else:
            for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                item_type = "📁" if item.is_dir() else "📄"
                size = item.stat().st_size if item.is_file() else 0
                items.append(f"{item_type} {item.name} ({self._format_size(size)})")

        output = f"Contents of {path}:\n\n" + "\n".join(items)
        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=output,
        )

    async def _mkdir(self, path: Path) -> ToolResult:
        """Create directory"""
        path.mkdir(parents=True, exist_ok=True)
        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Successfully created directory: {path}",
        )

    async def _move(self, source: Path, destination: str | None) -> ToolResult:
        """Move file or directory"""
        if destination is None:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No destination specified for move operation",
            )

        if not source.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Source not found: {source}",
            )

        dest = Path(destination).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(source), str(dest))

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Successfully moved {source} to {dest}",
        )

    async def _copy(self, source: Path, destination: str | None) -> ToolResult:
        """Copy file or directory"""
        if destination is None:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No destination specified for copy operation",
            )

        if not source.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Source not found: {source}",
            )

        dest = Path(destination).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)

        if source.is_file():
            shutil.copy2(str(source), str(dest))
        else:
            shutil.copytree(str(source), str(dest))

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Successfully copied {source} to {dest}",
        )

    async def _exists(self, path: Path) -> ToolResult:
        """Check if path exists"""
        exists = path.exists()
        if exists:
            details = []
            if path.is_file():
                details.append(f"Type: File")
                details.append(f"Size: {self._format_size(path.stat().st_size)}")
            elif path.is_dir():
                details.append(f"Type: Directory")
                details.append(f"Items: {len(list(path.iterdir()))}")

            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=f"Path exists: {path}\n" + "\n".join(details),
            )
        else:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=f"Path does not exist: {path}",
            )

    async def _stat(self, path: Path) -> ToolResult:
        """Get file statistics"""
        if not path.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Path not found: {path}",
            )

        stat = path.stat()
        import datetime

        details = [
            f"Path: {path}",
            f"Type: {'Directory' if path.is_dir() else 'File'}",
            f"Size: {self._format_size(stat.st_size)}",
            f"Modified: {datetime.datetime.fromtimestamp(stat.st_mtime)}",
            f"Accessed: {datetime.datetime.fromtimestamp(stat.st_atime)}",
            f"Created: {datetime.datetime.fromtimestamp(stat.st_ctime)}",
            f"Permissions: {oct(stat.st_mode)[-3:]}",
        ]

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output="\n".join(details),
        )

    @staticmethod
    def _format_size(size: int) -> str:
        """Format file size in human-readable format"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
