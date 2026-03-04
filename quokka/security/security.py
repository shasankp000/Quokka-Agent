"""
Security Layer implementation
Provides command allowlisting, directory restrictions, and audit logging
"""

from __future__ import annotations

import json
import os
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import SecurityDecision, ToolCall

logger = get_logger(__name__)


class AuditLogger:
    """
    Audit logger for security events

    Logs all security decisions and tool executions to a file
    """

    def __init__(self, log_dir: Path | None = None):
        """
        Initialize audit logger

        Args:
            log_dir: Directory for audit logs (defaults to config)
        """
        config = get_config()
        self.log_dir = log_dir or config.logging.file.parent / "audit"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = config.security.audit_log

    def log(
        self,
        event_type: str,
        tool_name: str,
        arguments: dict[str, Any],
        decision: SecurityDecision,
        user_id: int | str | None = None,
        session_id: str | None = None,
    ) -> None:
        """
        Log a security event

        Args:
            event_type: Type of event (check, execute, block)
            tool_name: Name of the tool
            arguments: Tool arguments
            decision: Security decision
            user_id: User ID (if available)
            session_id: Session ID (if available)
        """
        if not self.enabled:
            return

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "tool_name": tool_name,
            "arguments": self._sanitize_args(arguments),
            "decision": {
                "allowed": decision.allowed,
                "reason": decision.reason,
                "blocked_by": decision.blocked_by,
                "severity": decision.severity,
            },
            "user_id": str(user_id) if user_id else None,
            "session_id": session_id,
        }

        # Write to daily log file
        log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        # Also log to main logger
        if decision.allowed:
            logger.debug(f"Audit: {event_type} {tool_name} - {decision.reason}")
        else:
            logger.warning(f"Audit BLOCKED: {event_type} {tool_name} - {decision.reason}")

    def _sanitize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Sanitize arguments for logging (remove sensitive data)"""
        sensitive_keys = {"password", "token", "secret", "key", "credential"}
        result = {}
        for k, v in args.items():
            if any(s in k.lower() for s in sensitive_keys):
                result[k] = "***REDACTED***"
            elif isinstance(v, str) and len(v) > 200:
                result[k] = v[:200] + "...[truncated]"
            else:
                result[k] = v
        return result

    def get_recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent audit events"""
        events = []
        log_files = sorted(self.log_dir.glob("audit_*.jsonl"), reverse=True)

        for log_file in log_files:
            with open(log_file) as f:
                for line in f:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            if len(events) >= limit:
                break

        return events[-limit:]


class AllowlistChecker:
    """
    Command allowlist checker

    Validates shell commands against allowed and blocked command lists
    """

    def __init__(self) -> None:
        """Initialize allowlist checker"""
        config = get_config()
        self.allowed_commands = set(config.security.allowed_commands)
        self.blocked_commands = set(config.security.blocked_commands)
        self._is_admin = False

    def set_admin_mode(self, is_admin: bool) -> None:
        """Set admin mode (bypasses some restrictions)"""
        self._is_admin = is_admin

    def check_command(self, command: str) -> SecurityDecision:
        """
        Check if a command is allowed

        Args:
            command: The command to check

        Returns:
            SecurityDecision with result
        """
        if not command or not command.strip():
            return SecurityDecision(
                allowed=False,
                reason="Empty command",
                blocked_by="allowlist",
                severity="warning",
            )

        # Parse the command to get the base command
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return SecurityDecision(
                allowed=False,
                reason=f"Invalid command syntax: {e}",
                blocked_by="allowlist",
                severity="error",
            )

        if not parts:
            return SecurityDecision(
                allowed=False,
                reason="Empty command",
                blocked_by="allowlist",
                severity="warning",
            )

        base_cmd = os.path.basename(parts[0])

        # Check blocked commands first (even for admins)
        for blocked in self.blocked_commands:
            if blocked in command or blocked == base_cmd:
                return SecurityDecision(
                    allowed=False,
                    reason=f"Command '{blocked}' is blocked",
                    blocked_by="blocklist",
                    severity="critical",
                    warnings=["This command is permanently blocked for security"],
                )

        # Admin mode bypasses allowlist
        if self._is_admin:
            return SecurityDecision(
                allowed=True,
                reason="Admin mode - allowlist bypassed",
                severity="info",
            )

        # Check against allowlist
        if self.allowed_commands and base_cmd not in self.allowed_commands:
            return SecurityDecision(
                allowed=False,
                reason=f"Command '{base_cmd}' is not in allowlist",
                blocked_by="allowlist",
                severity="warning",
                warnings=[f"Allowed commands: {', '.join(sorted(self.allowed_commands))}"],
            )

        # Check for dangerous patterns
        dangerous_patterns = [
            (r'\brm\s+-rf\s+/', "Recursive deletion of root"),
            (r'\brm\s+-rf\s+~', "Recursive deletion of home"),
            (r'>\s*/etc/', "Writing to system config"),
            (r'chmod\s+777', "Insecure permissions"),
            (r'curl.*\|\s*(ba)?sh', "Remote code execution"),
            (r'wget.*\|\s*(ba)?sh', "Remote code execution"),
        ]

        warnings = []
        for pattern, desc in dangerous_patterns:
            if re.search(pattern, command):
                warnings.append(f"Potentially dangerous: {desc}")

        return SecurityDecision(
            allowed=True,
            reason="Command allowed",
            warnings=warnings,
            severity="warning" if warnings else "info",
        )


class DirectoryJail:
    """
    Directory access restriction

    Validates file paths against allowed and blocked directories
    """

    def __init__(self) -> None:
        """Initialize directory jail"""
        config = get_config()
        self.allowed_dirs = [Path(d).expanduser().resolve() for d in config.security.allowed_directories]
        self.blocked_dirs = [Path(d).expanduser().resolve() for d in config.security.blocked_directories]
        self._is_admin = False

    def set_admin_mode(self, is_admin: bool) -> None:
        """Set admin mode (bypasses some restrictions)"""
        self._is_admin = is_admin

    def check_path(self, path: str, operation: str = "access") -> SecurityDecision:
        """
        Check if a path is accessible

        Args:
            path: The path to check
            operation: The operation being performed (read, write, delete)

        Returns:
            SecurityDecision with result
        """
        if not path:
            return SecurityDecision(
                allowed=False,
                reason="Empty path",
                blocked_by="directory_jail",
                severity="warning",
            )

        try:
            target = Path(path).expanduser().resolve()
        except Exception as e:
            return SecurityDecision(
                allowed=False,
                reason=f"Invalid path: {e}",
                blocked_by="directory_jail",
                severity="error",
            )

        # Check blocked directories (even for admins)
        for blocked in self.blocked_dirs:
            try:
                target.relative_to(blocked)
                return SecurityDecision(
                    allowed=False,
                    reason=f"Path is in blocked directory: {blocked}",
                    blocked_by="directory_jail",
                    severity="critical",
                )
            except ValueError:
                pass

        # Admin mode bypasses allowed directory check
        if self._is_admin:
            return SecurityDecision(
                allowed=True,
                reason="Admin mode - directory restrictions bypassed",
                severity="info",
            )

        # Check against allowed directories
        if self.allowed_dirs:
            for allowed in self.allowed_dirs:
                try:
                    target.relative_to(allowed)
                    return SecurityDecision(
                        allowed=True,
                        reason="Path is within allowed directory",
                        severity="info",
                    )
                except ValueError:
                    pass

            return SecurityDecision(
                allowed=False,
                reason=f"Path is outside allowed directories",
                blocked_by="directory_jail",
                severity="warning",
                warnings=[f"Allowed directories: {', '.join(str(d) for d in self.allowed_dirs)}"],
            )

        # No restrictions if no allowed directories specified
        return SecurityDecision(
            allowed=True,
            reason="No directory restrictions configured",
            severity="info",
        )

    def sanitize_path(self, path: str) -> str:
        """
        Sanitize a path string

        - Expands ~ to home directory
        - Removes path traversal attempts
        - Normalizes the path
        """
        # Remove path traversal attempts
        path = path.replace("../", "").replace("/..", "")
        path = re.sub(r'\.{2,}', '.', path)

        # Expand home directory
        path = os.path.expanduser(path)

        # Normalize
        path = os.path.normpath(path)

        return path

    def is_sensitive_file(self, path: str) -> bool:
        """Check if a file is sensitive (should require confirmation)"""
        sensitive_patterns = [
            ".env",
            ".ssh",
            ".gnupg",
            ".pgp",
            "id_rsa",
            "id_ed25519",
            ".pem",
            ".key",
            "credentials",
            "secrets",
            "password",
        ]

        path_lower = path.lower()
        for pattern in sensitive_patterns:
            if pattern in path_lower:
                return True
        return False


class SecurityLayer:
    """
    Main security layer that combines all security checks

    Coordinates between:
    - AllowlistChecker for command validation
    - DirectoryJail for path validation
    - AuditLogger for logging
    """

    def __init__(self) -> None:
        """Initialize the security layer"""
        self.allowlist = AllowlistChecker()
        self.directory_jail = DirectoryJail()
        self.audit = AuditLogger()

        config = get_config()
        self.enabled = config.security.enabled
        self.dry_run_default = config.security.dry_run_default
        self.max_timeout = config.security.max_command_timeout

    def set_user_context(self, user_id: int | str, is_admin: bool = False) -> None:
        """
        Set the user context for security checks

        Args:
            user_id: The user ID
            is_admin: Whether the user is an admin
        """
        self.allowlist.set_admin_mode(is_admin)
        self.directory_jail.set_admin_mode(is_admin)
        self._current_user = user_id

    def check_tool_call(
        self,
        tool_call: ToolCall,
        session_id: str | None = None,
    ) -> SecurityDecision:
        """
        Check if a tool call is allowed

        Args:
            tool_call: The tool call to check
            session_id: Optional session ID for logging

        Returns:
            SecurityDecision with result
        """
        if not self.enabled:
            return SecurityDecision(allowed=True, reason="Security disabled")

        tool_name = tool_call.name
        args = tool_call.arguments

        # Tool-specific checks
        if tool_name == "shell_exec":
            command = args.get("command", "")
            decision = self.allowlist.check_command(command)

        elif tool_name == "file_ops":
            path = args.get("path", "")
            operation = args.get("operation", "read")
            decision = self.directory_jail.check_path(path, operation)

            # Check for sensitive files
            if decision.allowed and self.directory_jail.is_sensitive_file(path):
                decision.warnings.append("Sensitive file detected - requires confirmation")
                decision.requires_confirmation = True  # type: ignore

        elif tool_name in ("obsidian_read", "obsidian_write"):
            path = args.get("path", "") or args.get("vault_path", "")
            decision = self.directory_jail.check_path(path, "read" if "read" in tool_name else "write")

        else:
            # Default: allow with logging
            decision = SecurityDecision(allowed=True, reason="No specific restrictions for this tool")

        # Log the decision
        self.audit.log(
            event_type="check",
            tool_name=tool_name,
            arguments=args,
            decision=decision,
            user_id=getattr(self, "_current_user", None),
            session_id=session_id,
        )

        return decision

    def log_execution(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        success: bool,
        output: str | None = None,
        error: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """
        Log a tool execution

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            success: Whether execution succeeded
            output: Tool output (if any)
            error: Error message (if any)
            session_id: Session ID
        """
        decision = SecurityDecision(
            allowed=success,
            reason=error or "Execution completed",
            severity="error" if error else "info",
        )

        self.audit.log(
            event_type="execute" if success else "error",
            tool_name=tool_name,
            arguments=arguments,
            decision=decision,
            user_id=getattr(self, "_current_user", None),
            session_id=session_id,
        )

    def validate_timeout(self, timeout: int | None) -> int:
        """
        Validate and return a safe timeout value

        Args:
            timeout: Requested timeout

        Returns:
            Validated timeout within limits
        """
        if timeout is None or timeout <= 0:
            return 60  # Default

        return min(timeout, self.max_timeout)

    def should_confirm(self, tool_call: ToolCall) -> bool:
        """
        Determine if a tool call requires user confirmation

        Args:
            tool_call: The tool call to check

        Returns:
            True if confirmation is required
        """
        # Dangerous operations always require confirmation
        dangerous_tools = {"shell_exec"}
        if tool_call.name in dangerous_tools:
            return True

        # Check for sensitive file operations
        if tool_call.name == "file_ops":
            operation = tool_call.arguments.get("operation", "")
            if operation in ("write", "delete", "move"):
                return True

            path = tool_call.arguments.get("path", "")
            if self.directory_jail.is_sensitive_file(path):
                return True

        return False
