"""
Telegram Bot Transport Layer
Handles communication with users via Telegram
"""

from __future__ import annotations

import asyncio
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Coroutine

import httpx
from telegram import (
    Bot,
    Update,
    Message as TGMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import Message, MessageType

logger = get_logger(__name__)


class TelegramBot:
    """
    Telegram bot for user interaction

    Features:
    - Long polling for updates
    - User allowlist for security
    - Command handling
    - File/photo reception
    - Inline keyboards for confirmations
    """

    def __init__(self, message_handler: Callable[[Message, int], Coroutine[None, None, Message]]):
        """
        Initialize the Telegram bot

        Args:
            message_handler: Async callback to handle incoming messages
        """
        self.config = get_config()
        self.message_handler = message_handler

        self.bot: Bot | None = None
        self.application: Application | None = None
        self._running = False

        # Pending confirmations: callback_data -> (tool_call_id, user_id)
        self._pending_confirmations: dict[str, tuple[str, int]] = {}
        self._confirmation_callbacks: dict[str, Callable[[bool], Coroutine[None, None, None]]] = {}

    async def start(self) -> None:
        """Start the Telegram bot"""
        if not self.config.telegram.token:
            raise ValueError("Telegram bot token not configured. Set QUOKKA_TELEGRAM__TOKEN or config.telegram.token")

        self.bot = Bot(token=self.config.telegram.token)
        self.application = (
            Application.builder()
            .token(self.config.telegram.token)
            .read_timeout(self.config.telegram.polling_timeout)
            .write_timeout(30)
            .connect_timeout(30)
            .build()
        )

        # Register handlers
        self._register_handlers()

        # Initialize and start
        await self.application.initialize()
        await self.application.start()

        # Start polling
        await self.application.updater.start_polling(
            timeout=self.config.telegram.polling_timeout,
            poll_interval=self.config.telegram.polling_interval,
            allowed_updates=Update.ALL_TYPES,
        )

        self._running = True
        logger.info(f"Telegram bot started (bot: {await self.bot.get_me()})")

    async def stop(self) -> None:
        """Stop the Telegram bot"""
        self._running = False

        if self.application:
            if self.application.updater and self.application.updater.running:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

        logger.info("Telegram bot stopped")

    def _register_handlers(self) -> None:
        """Register all command and message handlers"""
        if not self.application:
            return

        # Commands
        self.application.add_handler(CommandHandler("start", self._handle_start))
        self.application.add_handler(CommandHandler("help", self._handle_help))
        self.application.add_handler(CommandHandler("status", self._handle_status))
        self.application.add_handler(CommandHandler("dryrun", self._handle_dryrun))
        self.application.add_handler(CommandHandler("clear", self._handle_clear))
        self.application.add_handler(CommandHandler("cancel", self._handle_cancel))

        # Callback queries (for inline keyboards)
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))

        # Messages (text, photos, documents)
        self.application.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self.application.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))

    def _is_allowed_user(self, user_id: int) -> bool:
        """Check if user is allowed to interact with the bot"""
        allowed = self.config.telegram.allowed_users
        admins = self.config.telegram.admin_users

        # If no allowlist, allow everyone (not recommended for production)
        if not allowed and not admins:
            logger.warning(f"No allowlist configured, allowing user {user_id}")
            return True

        return user_id in allowed or user_id in admins

    def _is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in self.config.telegram.admin_users

    async def _handle_start(self, update: Update, context: Any) -> None:
        """Handle /start command"""
        if not update.effective_user or not update.effective_message:
            return

        user_id = update.effective_user.id
        if not self._is_allowed_user(user_id):
            await update.effective_message.reply_text(
                "⛔ You are not authorized to use this bot."
            )
            return

        welcome = (
            "🦘 **Welcome to Quokka Agent!**\n\n"
            "I'm your local automation assistant. I can help you:\n"
            "• Execute shell commands\n"
            "• Manage files\n"
            "• Search and edit Obsidian notes\n"
            "• Process documents (PDFs, images)\n"
            "• And more!\n\n"
            "**Commands:**\n"
            "/help - Show detailed help\n"
            "/status - Show current session status\n"
            "/dryrun - Toggle dry-run mode (preview actions)\n"
            "/clear - Clear conversation history\n"
            "/cancel - Cancel current operation\n\n"
            "Just send me a message to get started!"
        )
        await update.effective_message.reply_text(welcome, parse_mode=ParseMode.MARKDOWN)

    async def _handle_help(self, update: Update, context: Any) -> None:
        """Handle /help command"""
        if not update.effective_user or not update.effective_message:
            return

        user_id = update.effective_user.id
        if not self._is_allowed_user(user_id):
            return

        help_text = (
            "🦘 **Quokka Agent Help**\n\n"
            "**Available Tools:**\n"
            "• `shell_exec` - Run shell commands\n"
            "• `file_ops` - Read, write, list files\n"
            "• `obsidian_read` - Search and read Obsidian notes\n"
            "• `obsidian_write` - Create/update Obsidian notes\n"
            "• `pdf_handler` - Extract text from PDFs\n"
            "• `web_fetch` - Make HTTP requests\n\n"
            "**Safety Features:**\n"
            "• Command allowlist/blocklist\n"
            "• Directory restrictions\n"
            "• Dry-run mode for previewing actions\n"
            "• Audit logging\n\n"
            "**Tips:**\n"
            "• Send photos for OCR processing\n"
            "• Send PDFs for text extraction\n"
            "• Use /dryrun to preview before executing"
        )
        await update.effective_message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def _handle_status(self, update: Update, context: Any) -> None:
        """Handle /status command"""
        if not update.effective_user or not update.effective_message:
            return

        user_id = update.effective_user.id
        if not self._is_allowed_user(user_id):
            return

        # TODO: Get actual session status
        status = (
            "📊 **Session Status**\n\n"
            f"User ID: `{user_id}`\n"
            f"Admin: {'Yes' if self._is_admin(user_id) else 'No'}\n"
            "Mode: Normal\n"
            "Pending tasks: 0"
        )
        await update.effective_message.reply_text(status, parse_mode=ParseMode.MARKDOWN)

    async def _handle_dryrun(self, update: Update, context: Any) -> None:
        """Handle /dryrun command to toggle dry-run mode"""
        if not update.effective_user or not update.effective_message:
            return

        user_id = update.effective_user.id
        if not self._is_allowed_user(user_id):
            return

        # TODO: Actually toggle dry-run mode in session
        await update.effective_message.reply_text(
            "🔄 Dry-run mode toggled. Commands will be previewed before execution."
        )

    async def _handle_clear(self, update: Update, context: Any) -> None:
        """Handle /clear command to clear conversation history"""
        if not update.effective_user or not update.effective_message:
            return

        user_id = update.effective_user.id
        if not self._is_allowed_user(user_id):
            return

        # TODO: Actually clear session
        await update.effective_message.reply_text(
            "🗑️ Conversation history cleared."
        )

    async def _handle_cancel(self, update: Update, context: Any) -> None:
        """Handle /cancel command to cancel current operation"""
        if not update.effective_user or not update.effective_message:
            return

        user_id = update.effective_user.id
        if not self._is_allowed_user(user_id):
            return

        await update.effective_message.reply_text(
            "❌ Current operation cancelled."
        )

    async def _handle_callback(self, update: Update, context: Any) -> None:
        """Handle inline keyboard callbacks"""
        if not update.callback_query or not update.effective_user:
            return

        query = update.callback_query
        user_id = update.effective_user.id

        if not self._is_allowed_user(user_id):
            await query.answer("Not authorized", show_alert=True)
            return

        await query.answer()

        callback_data = query.data
        if not callback_data:
            return

        # Handle confirmation callbacks
        if callback_data.startswith("confirm:"):
            parts = callback_data.split(":")
            if len(parts) >= 3:
                call_id = parts[1]
                approved = parts[2] == "yes"

                if call_id in self._confirmation_callbacks:
                    callback = self._confirmation_callbacks.pop(call_id)
                    await callback(approved)

                    # Update the message
                    if query.message:
                        status = "✅ Approved" if approved else "❌ Rejected"
                        await query.message.edit_text(
                            f"{query.message.text}\n\n{status}",
                            parse_mode=ParseMode.MARKDOWN,
                        )

    async def _handle_text(self, update: Update, context: Any) -> None:
        """Handle text messages"""
        if not update.effective_user or not update.effective_message or not update.effective_message.text:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else user_id

        if not self._is_allowed_user(user_id):
            await update.effective_message.reply_text("⛔ Not authorized.")
            return

        text = update.effective_message.text

        # Create message object
        message = Message(
            role=MessageType.USER,
            content=text,
            metadata={"chat_id": chat_id, "user_id": user_id},
        )

        # Show typing indicator
        if self.bot:
            await self.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Process message
        try:
            response = await self.message_handler(message, user_id)
            await self._send_response(chat_id, response)
        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            await update.effective_message.reply_text(
                f"❌ Error: {str(e)}",
                parse_mode=ParseMode.MARKDOWN,
            )

    async def _handle_photo(self, update: Update, context: Any) -> None:
        """Handle photo messages for OCR"""
        if not update.effective_user or not update.effective_message:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else user_id

        if not self._is_allowed_user(user_id):
            await update.effective_message.reply_text("⛔ Not authorized.")
            return

        photos = update.effective_message.photo
        if not photos:
            return

        # Get the largest photo
        photo = photos[-1]

        try:
            # Download the photo
            file = await photo.get_file()
            photo_bytes = BytesIO()
            await file.download_to_memory(photo_bytes)
            photo_bytes.seek(0)

            # Create message with image
            caption = update.effective_message.caption or "Process this image"

            message = Message(
                role=MessageType.USER,
                content=f"[Image received] {caption}",
                metadata={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "image_data": photo_bytes.getvalue(),
                    "image_for_ocr": True,
                },
            )

            # Process
            if self.bot:
                await self.bot.send_chat_action(chat_id=chat_id, action="typing")

            response = await self.message_handler(message, user_id)
            await self._send_response(chat_id, response)

        except Exception as e:
            logger.exception(f"Error processing photo: {e}")
            await update.effective_message.reply_text(f"❌ Error processing image: {str(e)}")

    async def _handle_document(self, update: Update, context: Any) -> None:
        """Handle document messages (PDFs, etc.)"""
        if not update.effective_user or not update.effective_message or not update.effective_message.document:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else user_id

        if not self._is_allowed_user(user_id):
            await update.effective_message.reply_text("⛔ Not authorized.")
            return

        document = update.effective_message.document

        try:
            # Download the document
            file = await document.get_file()
            doc_bytes = BytesIO()
            await file.download_to_memory(doc_bytes)
            doc_bytes.seek(0)

            filename = document.file_name or "document"
            caption = update.effective_message.caption or f"Process this document: {filename}"

            message = Message(
                role=MessageType.USER,
                content=f"[Document: {filename}] {caption}",
                metadata={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "document_data": doc_bytes.getvalue(),
                    "document_filename": filename,
                    "document_mime": document.mime_type,
                },
            )

            # Process
            if self.bot:
                await self.bot.send_chat_action(chat_id=chat_id, action="typing")

            response = await self.message_handler(message, user_id)
            await self._send_response(chat_id, response)

        except Exception as e:
            logger.exception(f"Error processing document: {e}")
            await update.effective_message.reply_text(f"❌ Error processing document: {str(e)}")

    async def _send_response(self, chat_id: int, message: Message) -> None:
        """Send a response message to the user"""
        if not self.bot:
            return

        text = message.content

        # Split long messages
        max_length = 4000
        messages = []

        if len(text) > max_length:
            # Split by paragraphs or sentences
            chunks = re.split(r'\n\n|\n', text)
            current = ""
            for chunk in chunks:
                if len(current) + len(chunk) + 2 <= max_length:
                    current += chunk + "\n\n"
                else:
                    if current:
                        messages.append(current.strip())
                    current = chunk + "\n\n"
            if current:
                messages.append(current.strip())
        else:
            messages.append(text)

        for msg_text in messages:
            if msg_text:
                # Escape markdown special characters for better display
                # But preserve code blocks
                if "```" not in msg_text:
                    msg_text = self._escape_markdown(msg_text)
                    await self.bot.send_message(chat_id=chat_id, text=msg_text, parse_mode=ParseMode.MARKDOWN_V2)
                else:
                    await self.bot.send_message(chat_id=chat_id, text=msg_text, parse_mode=ParseMode.MARKDOWN)

        # Handle tool results with confirmation requests
        if message.tool_calls:
            for tc in message.tool_calls:
                if tc.requires_confirmation:
                    await self._send_confirmation(chat_id, tc)

    def _escape_markdown(self, text: str) -> str:
        """Escape markdown special characters for MarkdownV2"""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text

    async def _send_confirmation(self, chat_id: int, tool_call: Any) -> None:
        """Send an inline keyboard for confirmation"""
        if not self.bot:
            return

        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"confirm:{tool_call.id}:yes"),
                InlineKeyboardButton("❌ Reject", callback_data=f"confirm:{tool_call.id}:no"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        args_str = "\n".join(f"  {k}: {v}" for k, v in tool_call.arguments.items())

        text = (
            f"⚠️ **Confirmation Required**\n\n"
            f"Tool: `{tool_call.name}`\n"
            f"Arguments:\n```\n{args_str}\n```\n\n"
            "Approve this action?"
        )

        await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
        )

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a simple text message"""
        if self.bot:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)

    async def send_file(self, chat_id: int, filepath: Path, caption: str = "") -> None:
        """Send a file to the user"""
        if self.bot and filepath.exists():
            with open(filepath, "rb") as f:
                await self.bot.send_document(chat_id=chat_id, document=f, caption=caption)

    def register_confirmation_callback(
        self, call_id: str, callback: Callable[[bool], Coroutine[None, None, None]]
    ) -> None:
        """Register a callback for a confirmation request"""
        self._confirmation_callbacks[call_id] = callback
