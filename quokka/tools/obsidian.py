"""
Obsidian integration tools

Tools for reading and writing Obsidian notes
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from ..core.config import get_config
from ..core.types import ToolResult
from ..core.logger import get_logger
from .base import BaseTool

logger = get_logger(__name__)


class ObsidianReadTool(BaseTool):
    """
    Read and search Obsidian notes
    """

    name: ClassVar[str] = "obsidian_read"
    description: ClassVar[str] = (
        "Read and search Obsidian notes in a vault. "
        "Operations: get, search, list, backlinks. "
        "Returns note content or search results."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["get", "search", "list", "backlinks", "tags"],
                "description": "The operation to perform",
            },
            "path": {
                "type": "string",
                "description": "Note path (relative to vault) for 'get' operation",
            },
            "query": {
                "type": "string",
                "description": "Search query for 'search' operation",
            },
            "tag": {
                "type": "string",
                "description": "Tag to search for",
            },
            "vault_path": {
                "type": "string",
                "description": "Path to Obsidian vault (optional if configured)",
            },
        },
        "required": ["operation"],
    }

    def __init__(self) -> None:
        """Initialize the Obsidian read tool"""
        # Try to find vault from config or environment
        self._vault_path: Path | None = None

    def _get_vault_path(self, vault_path: str | None = None) -> Path:
        """Get the Obsidian vault path"""
        if vault_path:
            return Path(vault_path).expanduser().resolve()

        if self._vault_path:
            return self._vault_path

        # Try environment variable
        env_vault = os.getenv("OBSIDIAN_VAULT")
        if env_vault:
            self._vault_path = Path(env_vault).expanduser().resolve()
            return self._vault_path

        # Try common locations
        common_paths = [
            Path.home() / "Documents" / "Obsidian",
            Path.home() / "obsidian",
            Path.home() / ".obsidian",
        ]

        for path in common_paths:
            if path.exists():
                # Look for vault directories
                for vault in path.iterdir():
                    if vault.is_dir() and (vault / ".obsidian").exists():
                        self._vault_path = vault
                        return vault

        raise ValueError(
            "Obsidian vault not found. Set OBSIDIAN_VAULT environment variable "
            "or provide vault_path parameter."
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute Obsidian read operation

        Args:
            operation: The operation to perform
            path: Note path for get operation
            query: Search query
            tag: Tag to search
            vault_path: Path to vault

        Returns:
            ToolResult with note content or search results
        """
        operation = kwargs.get("operation", "")

        try:
            vault = self._get_vault_path(kwargs.get("vault_path"))
        except ValueError as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=str(e),
            )

        if operation == "get":
            return await self._get_note(vault, kwargs.get("path", ""))
        elif operation == "search":
            return await self._search_notes(vault, kwargs.get("query", ""))
        elif operation == "list":
            return await self._list_notes(vault)
        elif operation == "backlinks":
            return await self._get_backlinks(vault, kwargs.get("path", ""))
        elif operation == "tags":
            return await self._get_by_tag(vault, kwargs.get("tag", ""))
        else:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Unknown operation: {operation}",
            )

    async def _get_note(self, vault: Path, note_path: str) -> ToolResult:
        """Get a specific note by path"""
        if not note_path:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No note path provided",
            )

        # Add .md extension if not present
        if not note_path.endswith(".md"):
            note_path += ".md"

        note_file = vault / note_path

        if not note_file.exists():
            # Try to find by filename
            matches = list(vault.rglob(note_path.split("/")[-1]))
            if matches:
                note_file = matches[0]
            else:
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=False,
                    error=f"Note not found: {note_path}",
                )

        try:
            content = note_file.read_text(encoding="utf-8")

            # Parse frontmatter
            frontmatter = {}
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    try:
                        frontmatter = yaml.safe_load(parts[1]) or {}
                    except Exception:
                        pass

            # Extract metadata
            output_parts = [
                f"📝 Note: {note_path}",
                f"Path: {note_file.relative_to(vault)}",
                f"Modified: {datetime.fromtimestamp(note_file.stat().st_mtime)}",
            ]

            if frontmatter:
                output_parts.append("\n📋 Frontmatter:")
                for key, value in frontmatter.items():
                    output_parts.append(f"  {key}: {value}")

            output_parts.append("\n--- Content ---\n")
            output_parts.append(content)

            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output="\n".join(output_parts),
            )

        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Failed to read note: {e}",
            )

    async def _search_notes(self, vault: Path, query: str) -> ToolResult:
        """Search notes by content"""
        if not query:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No search query provided",
            )

        results = []
        query_lower = query.lower()

        for md_file in vault.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if query_lower in content.lower():
                    rel_path = md_file.relative_to(vault)

                    # Find context around the match
                    idx = content.lower().find(query_lower)
                    start = max(0, idx - 100)
                    end = min(len(content), idx + len(query) + 100)
                    context = content[start:end].replace("\n", " ")

                    results.append(f"📄 {rel_path}\n   ...{context}...\n")
            except Exception:
                continue

        if not results:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=f"No notes found matching: {query}",
            )

        output = f"🔍 Search results for '{query}' ({len(results)} found):\n\n"
        output += "\n".join(results[:20])  # Limit to 20 results

        if len(results) > 20:
            output += f"\n\n... and {len(results) - 20} more results"

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=output,
        )

    async def _list_notes(self, vault: Path) -> ToolResult:
        """List all notes in the vault"""
        notes = []

        for md_file in vault.rglob("*.md"):
            rel_path = md_file.relative_to(vault)
            stat = md_file.stat()
            notes.append({
                "path": str(rel_path),
                "modified": datetime.fromtimestamp(stat.st_mtime),
                "size": stat.st_size,
            })

        # Sort by modification time
        notes.sort(key=lambda x: x["modified"], reverse=True)

        output_parts = [f"📚 Obsidian Vault: {vault}\n"]
        output_parts.append(f"Total notes: {len(notes)}\n")
        output_parts.append("Recent notes:")

        for note in notes[:30]:
            output_parts.append(f"  📄 {note['path']} ({note['size']} bytes)")

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output="\n".join(output_parts),
        )

    async def _get_backlinks(self, vault: Path, note_path: str) -> ToolResult:
        """Find backlinks to a note"""
        if not note_path:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No note path provided",
            )

        # Get the note name without extension
        note_name = Path(note_path).stem
        link_pattern = re.compile(rf'\[\[({re.escape(note_name)})(?:\|[^\]]+)?\]\]', re.IGNORECASE)

        backlinks = []

        for md_file in vault.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if link_pattern.search(content):
                    rel_path = md_file.relative_to(vault)
                    backlinks.append(f"  📄 {rel_path}")
            except Exception:
                continue

        if not backlinks:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=f"No backlinks found to: {note_path}",
            )

        output = f"🔗 Backlinks to '{note_path}' ({len(backlinks)} found):\n\n"
        output += "\n".join(backlinks)

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=output,
        )

    async def _get_by_tag(self, vault: Path, tag: str) -> ToolResult:
        """Find notes with a specific tag"""
        if not tag:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No tag provided",
            )

        # Normalize tag
        if not tag.startswith("#"):
            tag = "#" + tag

        tag_pattern = re.compile(re.escape(tag), re.IGNORECASE)
        results = []

        for md_file in vault.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if tag_pattern.search(content):
                    rel_path = md_file.relative_to(vault)
                    results.append(f"  📄 {rel_path}")
            except Exception:
                continue

        if not results:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=f"No notes found with tag: {tag}",
            )

        output = f"🏷️ Notes with tag '{tag}' ({len(results)} found):\n\n"
        output += "\n".join(results)

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=output,
        )


class ObsidianWriteTool(BaseTool):
    """
    Create and update Obsidian notes
    """

    name: ClassVar[str] = "obsidian_write"
    description: ClassVar[str] = (
        "Create or update Obsidian notes. "
        "Operations: create, update, append, prepend. "
        "Supports frontmatter and wiki links."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "update", "append", "prepend"],
                "description": "The operation to perform",
                "default": "create",
            },
            "path": {
                "type": "string",
                "description": "Note path (relative to vault)",
            },
            "content": {
                "type": "string",
                "description": "Note content",
            },
            "frontmatter": {
                "type": "object",
                "description": "YAML frontmatter to add/update",
            },
            "vault_path": {
                "type": "string",
                "description": "Path to Obsidian vault (optional if configured)",
            },
        },
        "required": ["path", "content"],
    }

    requires_confirmation: bool = True

    def __init__(self) -> None:
        """Initialize the Obsidian write tool"""
        self._vault_path: Path | None = None

    def _get_vault_path(self, vault_path: str | None = None) -> Path:
        """Get the Obsidian vault path"""
        if vault_path:
            return Path(vault_path).expanduser().resolve()

        if self._vault_path:
            return self._vault_path

        env_vault = os.getenv("OBSIDIAN_VAULT")
        if env_vault:
            self._vault_path = Path(env_vault).expanduser().resolve()
            return self._vault_path

        raise ValueError("Obsidian vault not found. Set OBSIDIAN_VAULT environment variable.")

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute Obsidian write operation

        Args:
            operation: The operation to perform
            path: Note path
            content: Note content
            frontmatter: YAML frontmatter
            vault_path: Path to vault

        Returns:
            ToolResult with operation status
        """
        operation = kwargs.get("operation", "create")
        note_path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        frontmatter = kwargs.get("frontmatter")

        if not note_path:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No note path provided",
            )

        try:
            vault = self._get_vault_path(kwargs.get("vault_path"))
        except ValueError as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=str(e),
            )

        # Ensure .md extension
        if not note_path.endswith(".md"):
            note_path += ".md"

        note_file = vault / note_path

        try:
            if operation == "create":
                return await self._create_note(note_file, content, frontmatter)
            elif operation == "update":
                return await self._update_note(note_file, content, frontmatter)
            elif operation == "append":
                return await self._append_note(note_file, content)
            elif operation == "prepend":
                return await self._prepend_note(note_file, content)
            else:
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=False,
                    error=f"Unknown operation: {operation}",
                )
        except Exception as e:
            logger.exception(f"Obsidian write failed: {e}")
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=str(e),
            )

    async def _create_note(
        self, note_file: Path, content: str, frontmatter: dict[str, Any] | None
    ) -> ToolResult:
        """Create a new note"""
        if note_file.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Note already exists: {note_file}",
            )

        # Create parent directories
        note_file.parent.mkdir(parents=True, exist_ok=True)

        # Build content with frontmatter
        final_content = self._build_content(content, frontmatter)

        note_file.write_text(final_content, encoding="utf-8")

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Created note: {note_file.relative_to(note_file.parent.parent)}",
        )

    async def _update_note(
        self, note_file: Path, content: str, frontmatter: dict[str, Any] | None
    ) -> ToolResult:
        """Update an existing note"""
        if not note_file.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Note not found: {note_file}",
            )

        existing = note_file.read_text(encoding="utf-8")

        # Preserve existing frontmatter if not overridden
        if not frontmatter and existing.startswith("---"):
            parts = existing.split("---", 2)
            if len(parts) >= 3:
                # Keep existing frontmatter, update content
                final_content = f"---{parts[1]}---\n{content}"
            else:
                final_content = content
        else:
            final_content = self._build_content(content, frontmatter)

        note_file.write_text(final_content, encoding="utf-8")

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Updated note: {note_file.name}",
        )

    async def _append_note(self, note_file: Path, content: str) -> ToolResult:
        """Append content to a note"""
        if not note_file.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Note not found: {note_file}",
            )

        existing = note_file.read_text(encoding="utf-8")

        # Ensure newline before appending
        if not existing.endswith("\n"):
            existing += "\n"

        note_file.write_text(existing + content, encoding="utf-8")

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Appended to note: {note_file.name}",
        )

    async def _prepend_note(self, note_file: Path, content: str) -> ToolResult:
        """Prepend content to a note"""
        if not note_file.exists():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Note not found: {note_file}",
            )

        existing = note_file.read_text(encoding="utf-8")

        # Handle frontmatter
        if existing.startswith("---"):
            parts = existing.split("---", 2)
            if len(parts) >= 3:
                # Prepend after frontmatter
                final_content = f"---{parts[1]}---\n{content}\n{parts[2]}"
            else:
                final_content = content + "\n" + existing
        else:
            final_content = content + "\n" + existing

        note_file.write_text(final_content, encoding="utf-8")

        return ToolResult(
            call_id="",
            tool_name=self.name,
            success=True,
            output=f"Prepended to note: {note_file.name}",
        )

    def _build_content(self, content: str, frontmatter: dict[str, Any] | None) -> str:
        """Build note content with frontmatter"""
        if not frontmatter:
            return content

        import yaml

        fm_str = yaml.dump(frontmatter, default_flow_style=False)
        return f"---\n{fm_str}---\n\n{content}"
