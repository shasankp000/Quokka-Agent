"""
Session Manager - Manages conversation sessions
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import Message, MessageType, Session

logger = get_logger(__name__)


class SessionManager:
    """
    Manages conversation sessions

    Features:
    - Persist sessions to disk
    - Auto-expire old sessions
    - Context window management
    - Session recovery
    """

    def __init__(self, session_dir: Path | None = None) -> None:
        """
        Initialize the session manager

        Args:
            session_dir: Directory for session storage
        """
        self.config = get_config()
        self.session_dir = session_dir or self.config.memory.session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._sessions: dict[str | int, Session] = {}
        self._lock = asyncio.Lock()

        # Load existing sessions
        self._load_sessions()

    def _load_sessions(self) -> None:
        """Load existing sessions from disk"""
        for session_file in self.session_dir.glob("*.json"):
            try:
                session = Session.from_json(session_file.read_text())
                self._sessions[session.user_id] = session
                logger.debug(f"Loaded session: {session.id}")
            except Exception as e:
                logger.warning(f"Failed to load session {session_file}: {e}")

    async def get_or_create(
        self,
        user_id: int | str,
        chat_id: int | str,
    ) -> Session:
        """
        Get existing session or create a new one

        Args:
            user_id: User identifier
            chat_id: Chat identifier

        Returns:
            Session object
        """
        async with self._lock:
            # Check for existing session
            if user_id in self._sessions:
                session = self._sessions[user_id]

                # Check if session is expired
                age = datetime.now() - session.updated_at
                if age > timedelta(hours=self.config.memory.session_ttl_hours):
                    logger.info(f"Session expired for user {user_id}, creating new")
                    session = await self._create_session(user_id, chat_id)
                else:
                    logger.debug(f"Using existing session for user {user_id}")

                return session

            # Create new session
            return await self._create_session(user_id, chat_id)

    async def _create_session(
        self,
        user_id: int | str,
        chat_id: int | str,
    ) -> Session:
        """Create a new session"""
        session = Session(
            id=f"sess_{uuid4().hex[:8]}",
            user_id=user_id,
            chat_id=chat_id,
            dry_run_mode=self.config.security.dry_run_default,
        )

        self._sessions[user_id] = session
        await self.save(session)

        logger.info(f"Created new session: {session.id} for user {user_id}")

        return session

    async def save(self, session: Session) -> None:
        """
        Save a session to disk

        Args:
            session: Session to save
        """
        async with self._lock:
            session.updated_at = datetime.now()
            filepath = session.save(self.session_dir)
            logger.debug(f"Saved session to {filepath}")

    async def add_message(
        self,
        session: Session,
        message: Message,
    ) -> None:
        """
        Add a message to a session

        Args:
            session: Session to update
            message: Message to add
        """
        session.add_message(message)

        # Trim if over limit
        max_messages = self.config.memory.max_session_messages
        if len(session.messages) > max_messages:
            # Keep system messages and recent messages
            system_msgs = [m for m in session.messages if m.role == MessageType.SYSTEM]
            recent_msgs = [m for m in session.messages if m.role != MessageType.SYSTEM][-max_messages:]
            session.messages = system_msgs + recent_msgs

        await self.save(session)

    async def get_context(
        self,
        session: Session,
        max_messages: int | None = None,
    ) -> list[Message]:
        """
        Get context window for a session

        Args:
            session: Session to get context from
            max_messages: Maximum messages (defaults to config)

        Returns:
            List of messages for context
        """
        max_messages = max_messages or self.config.memory.max_session_messages
        return session.get_context_window(max_messages)

    async def clear(self, user_id: int | str) -> None:
        """
        Clear a user's session

        Args:
            user_id: User whose session to clear
        """
        async with self._lock:
            if user_id in self._sessions:
                session = self._sessions.pop(user_id)

                # Delete session file
                session_file = self.session_dir / f"{session.id}.json"
                if session_file.exists():
                    session_file.unlink()

                logger.info(f"Cleared session for user {user_id}")

    async def toggle_dry_run(self, user_id: int | str) -> bool:
        """
        Toggle dry-run mode for a session

        Args:
            user_id: User whose session to update

        Returns:
            New dry-run state
        """
        if user_id in self._sessions:
            session = self._sessions[user_id]
            session.dry_run_mode = not session.dry_run_mode
            await self.save(session)
            return session.dry_run_mode
        return False

    async def cleanup_expired(self) -> int:
        """
        Remove expired sessions

        Returns:
            Number of sessions removed
        """
        expired_count = 0
        threshold = datetime.now() - timedelta(hours=self.config.memory.session_ttl_hours)

        async with self._lock:
            to_remove = []

            for user_id, session in self._sessions.items():
                if session.updated_at < threshold:
                    to_remove.append(user_id)

            for user_id in to_remove:
                session = self._sessions.pop(user_id)
                session_file = self.session_dir / f"{session.id}.json"
                if session_file.exists():
                    session_file.unlink()
                expired_count += 1

        if expired_count:
            logger.info(f"Cleaned up {expired_count} expired sessions")

        return expired_count

    def get_active_count(self) -> int:
        """Get number of active sessions"""
        return len(self._sessions)

    def get_all_user_ids(self) -> list[int | str]:
        """Get all user IDs with active sessions"""
        return list(self._sessions.keys())
