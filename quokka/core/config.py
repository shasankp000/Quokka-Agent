"""
Configuration management using Pydantic Settings
Supports YAML config file with environment variable overrides
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class TelegramConfig(BaseModel):
    """Telegram bot configuration"""

    token: str = Field(default="", description="Bot token from BotFather")
    allowed_users: list[int] = Field(default_factory=list, description="Allowed Telegram user IDs")
    admin_users: list[int] = Field(default_factory=list, description="Admin user IDs with full access")
    polling_timeout: int = Field(default=30, description="Long polling timeout in seconds")
    polling_interval: float = Field(default=0.5, description="Interval between polls")


class OllamaConfig(BaseModel):
    """Ollama local LLM configuration"""

    base_url: str = Field(default="http://localhost:11434", description="Ollama API URL")
    model: str = Field(default="llama3.1:8b", description="Model to use for inference")
    timeout: int = Field(default=120, description="Request timeout in seconds")
    context_window: int = Field(default=8192, description="Context window size")
    temperature: float = Field(default=0.7, description="Temperature for generation")


class OpenRouterConfig(BaseModel):
    """OpenRouter cloud LLM configuration"""

    api_key: str = Field(default="", description="OpenRouter API key")
    base_url: str = Field(default="https://openrouter.ai/api/v1", description="OpenRouter API URL")
    model: str = Field(default="anthropic/claude-3.5-sonnet", description="Default model for complex tasks")
    timeout: int = Field(default=180, description="Request timeout in seconds")
    temperature: float = Field(default=0.7, description="Temperature for generation")


class RouterConfig(BaseModel):
    """LLM Router configuration"""

    complexity_threshold: float = Field(
        default=0.5,
        description="Threshold (0-1) for routing to cloud. Higher = more likely to use cloud",
    )
    always_local_tools: list[str] = Field(
        default_factory=lambda: ["shell_exec", "file_ops", "obsidian_read", "obsidian_write"],
        description="Tools that should always use local LLM for speed",
    )
    always_cloud_patterns: list[str] = Field(
        default_factory=lambda: ["complex reasoning", "code review", "detailed analysis"],
        description="Patterns that should always use cloud LLM",
    )


class SecurityConfig(BaseModel):
    """Security layer configuration"""

    enabled: bool = Field(default=True, description="Enable security checks")
    dry_run_default: bool = Field(default=False, description="Default dry-run mode state")
    allowed_commands: list[str] = Field(
        default_factory=lambda: [
            "ls", "cat", "head", "tail", "grep", "find", "pwd", "echo",
            "git", "python", "pip", "npm", "node", "bun", "code", "nvim",
            "mkdir", "touch", "cp", "mv", "rm", "chmod",
        ],
        description="Whitelisted commands for shell_exec",
    )
    blocked_commands: list[str] = Field(
        default_factory=lambda: ["sudo", "su", "passwd", "chmod 777", "dd", "mkfs"],
        description="Blocked commands that should never run",
    )
    allowed_directories: list[str] = Field(
        default_factory=lambda: ["~"],
        description="Directories the agent is allowed to access",
    )
    blocked_directories: list[str] = Field(
        default_factory=lambda: ["/etc/passwd", "/etc/shadow", "~/.ssh", "~/.gnupg"],
        description="Directories the agent cannot access",
    )
    max_command_timeout: int = Field(default=300, description="Maximum command execution time in seconds")
    audit_log: bool = Field(default=True, description="Enable audit logging")


class ExecutorConfig(BaseModel):
    """Tool executor configuration"""

    max_concurrent_tasks: int = Field(default=3, description="Maximum concurrent tool executions")
    default_timeout: int = Field(default=60, description="Default tool execution timeout")
    containerized: bool = Field(default=False, description="Use containerized execution (future feature)")
    output_poll_interval: float = Field(default=0.5, description="Interval for polling long-running tasks")


class MemoryConfig(BaseModel):
    """Memory and persistence configuration"""

    session_dir: Path = Field(default=Path("data/sessions"), description="Directory for session storage")
    task_queue_file: Path = Field(default=Path("data/tasks/queue.json"), description="Task queue file")
    max_session_messages: int = Field(default=100, description="Maximum messages per session")
    session_ttl_hours: int = Field(default=24, description="Session time-to-live in hours")


class MultimodalConfig(BaseModel):
    """Multimodal input configuration"""

    ocr_enabled: bool = Field(default=True, description="Enable OCR for images")
    ocr_language: str = Field(default="eng", description="Default OCR language")
    pdf_enabled: bool = Field(default=True, description="Enable PDF text extraction")
    max_image_size_mb: int = Field(default=10, description="Maximum image size in MB")
    max_pdf_size_mb: int = Field(default=50, description="Maximum PDF size in MB")


class LoggingConfig(BaseModel):
    """Logging configuration"""

    level: str = Field(default="INFO", description="Log level")
    file: Path = Field(default=Path("data/logs/agent.log"), description="Log file path")
    max_size_mb: int = Field(default=10, description="Maximum log file size")
    backup_count: int = Field(default=5, description="Number of backup log files")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string",
    )


class Config(BaseSettings):
    """Main configuration class"""

    # Environment
    environment: str = Field(default="development", description="Environment (development/production)")

    # Sub-configurations
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    multimodal: MultimodalConfig = Field(default_factory=MultimodalConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Paths
    config_file: Path = Field(default=Path("config/config.yaml"), description="Path to config file")

    model_config = {
        "env_prefix": "QUOKKA_",
        "env_nested_delimiter": "__",
        "extra": "ignore",
    }

    @field_validator("config_file", mode="before")
    @classmethod
    def validate_config_file(cls, v: Any) -> Path:
        return Path(v) if isinstance(v, str) else v

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        """Load configuration from YAML file"""
        if not path.exists():
            return cls()

        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def to_yaml(self, path: Path) -> None:
        """Save configuration to YAML file"""
        path.parent.mkdir(parents=True, exist_ok=True)

        def path_to_str(obj: Any) -> Any:
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, dict):
                return {k: path_to_str(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [path_to_str(item) for item in obj]
            return obj

        data = self.model_dump()
        data = path_to_str(data)
        # Remove config_file from saved config
        data.pop("config_file", None)

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def ensure_directories(self) -> None:
        """Create necessary directories"""
        import sys

        # Resolve paths - if relative, make them relative to a writable location
        # For systemd services, prefer /var/lib/quokka and /var/log/quokka
        var_lib = Path("/var/lib/quokka")
        var_log = Path("/var/log/quokka")

        # Helper to resolve path to an absolute, writable location
        def resolve_path(path: Path, fallback_dir: Path) -> Path:
            path = Path(path)
            if path.is_absolute():
                return path

            # Try the fallback directory first (for systemd services)
            if fallback_dir.exists() or fallback_dir.parent.exists():
                try:
                    fallback_dir.mkdir(parents=True, exist_ok=True)
                    return fallback_dir
                except (PermissionError, OSError):
                    pass

            # Try to make the relative path absolute from current working dir
            abs_path = path.resolve()
            try:
                abs_path.mkdir(parents=True, exist_ok=True)
                return abs_path
            except (PermissionError, OSError):
                pass

            # Last resort: use temp directory
            import tempfile
            temp_base = Path(tempfile.gettempdir()) / "quokka"
            temp_base.mkdir(parents=True, exist_ok=True)
            return temp_base / path.name

        # Resolve and create directories
        try:
            session_dir = resolve_path(self.memory.session_dir, var_lib / "sessions")
            self.memory.session_dir = session_dir
            session_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            print(f"Warning: Could not create session directory: {e}", file=sys.stderr)

        try:
            task_dir = resolve_path(self.memory.task_queue_file.parent, var_lib / "tasks")
            self.memory.task_queue_file = task_dir / "queue.json"
            task_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            print(f"Warning: Could not create task directory: {e}", file=sys.stderr)

        try:
            log_dir = resolve_path(self.logging.file.parent, var_log)
            self.logging.file = log_dir / "agent.log"
            log_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            print(f"Warning: Could not create log directory: {e}", file=sys.stderr)


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get or create the global configuration instance"""
    global _config

    if _config is None:
        config_file = Path(os.getenv("QUOKKA_CONFIG", "config/config.yaml"))

        # Try to load from YAML first, then fall back to env vars
        if config_file.exists():
            _config = Config.from_yaml(config_file)
        else:
            _config = Config()

        _config.ensure_directories()

    return _config


def reload_config() -> Config:
    """Reload configuration from file"""
    global _config
    _config = None
    return get_config()
