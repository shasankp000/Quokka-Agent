"""
Main entry point for Quokka Agent
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from .agent import QuokkaAgent
from .core.config import get_config
from .core.logger import get_logger
from .transport.telegram import TelegramBot

logger = get_logger(__name__)


async def main_async() -> None:
    """Main async entry point"""
    config = get_config()

    # Create agent
    agent = QuokkaAgent(config)

    # Start agent
    await agent.start()

    # Create message handler wrapper
    async def handle_message(message, user_id):
        return await agent.process_message(message, user_id)

    # Create and start Telegram bot if configured
    telegram: TelegramBot | None = None

    if config.telegram.token:
        telegram = TelegramBot(message_handler=handle_message)
        agent.set_telegram(telegram)

        try:
            await telegram.start()
            logger.info("Telegram bot started. Press Ctrl+C to stop.")

            # Keep running until interrupted
            while True:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Shutting down...")
        finally:
            await telegram.stop()
            await agent.stop()
    else:
        logger.warning(
            "No Telegram token configured. "
            "Set QUOKKA_TELEGRAM__TOKEN environment variable or configure in config.yaml"
        )
        logger.info("Running in headless mode...")

        # In headless mode, just keep the agent running
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        finally:
            await agent.stop()


def main() -> None:
    """Main entry point"""
    # Handle signals gracefully
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def signal_handler():
        logger.info("Received shutdown signal")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        loop.run_until_complete(main_async())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        loop.close()
        logger.info("Goodbye!")


if __name__ == "__main__":
    main()
