"""
Logging configuration with Rich support for beautiful console output
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

# Global console instance
console = Console()


class FileHandlerWithRotation(logging.Handler):
    """Simple file handler with size-based rotation"""

    def __init__(self, filepath: Path, max_size_mb: int = 10, backup_count: int = 5):
        super().__init__()
        self.filepath = filepath
        self.max_size = max_size_mb * 1024 * 1024
        self.backup_count = backup_count
        filepath.parent.mkdir(parents=True, exist_ok=True)
        self._file: Any = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) + "\n"

            # Check for rotation
            if self.filepath.exists() and self.filepath.stat().st_size > self.max_size:
                self._rotate()

            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            self.handleError(record)

    def _rotate(self) -> None:
        """Rotate log files"""
        for i in range(self.backup_count - 1, 0, -1):
            src = self.filepath.with_suffix(f".{i}.log")
            dst = self.filepath.with_suffix(f".{i + 1}.log")
            if src.exists():
                src.rename(dst)

        if self.filepath.exists():
            self.filepath.rename(self.filepath.with_suffix(".1.log"))


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    max_size_mb: int = 10,
    backup_count: int = 5,
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
) -> None:
    """
    Setup logging with Rich console output and optional file logging

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file
        max_size_mb: Maximum log file size before rotation
        backup_count: Number of backup files to keep
        log_format: Format string for log messages
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
    )
    rich_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(rich_handler)

    # File handler (if specified)
    if log_file:
        file_handler = FileHandlerWithRotation(
            filepath=log_file,
            max_size_mb=max_size_mb,
            backup_count=backup_count,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
