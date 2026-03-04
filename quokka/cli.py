#!/usr/bin/env python3
"""
Quokka Agent CLI

Provides command-line interface for managing the agent
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from quokka.core.config import Config, get_config
from quokka.core.logger import setup_logging


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize configuration file"""
    config_path = Path(args.config)

    if config_path.exists() and not args.force:
        print(f"Config file already exists: {config_path}")
        print("Use --force to overwrite")
        return

    # Create default config
    config = Config()

    # Set provided values
    if args.telegram_token:
        config.telegram.token = args.telegram_token

    if args.ollama_url:
        config.ollama.base_url = args.ollama_url

    if args.ollama_model:
        config.ollama.model = args.ollama_model

    if args.openrouter_key:
        config.openrouter.api_key = args.openrouter_key

    # Save config
    config.to_yaml(config_path)
    print(f"Created configuration file: {config_path}")
    print("\nNext steps:")
    print("1. Edit the config file to add your Telegram bot token")
    print("2. Make sure Ollama is running (or configure OpenRouter)")
    print("3. Run: quokka run")


def cmd_run(args: argparse.Namespace) -> None:
    """Run the agent"""
    from quokka.__main__ import main_async

    # Setup logging
    config = get_config()
    setup_logging(
        level=config.logging.level,
        log_file=config.logging.file,
    )

    # Run the agent
    asyncio.run(main_async())


def cmd_config(args: argparse.Namespace) -> None:
    """Show or modify configuration"""
    config = get_config()

    if args.show:
        print("Current configuration:")
        print(yaml.dump(config.model_dump(), default_flow_style=False))
    elif args.set:
        # Parse key=value
        for item in args.set:
            if "=" not in item:
                print(f"Invalid format: {item}. Use key=value")
                continue

            key, value = item.split("=", 1)
            parts = key.split(".")

            # Navigate to the right place
            obj = config
            for part in parts[:-1]:
                obj = getattr(obj, part)

            # Set the value
            setattr(obj, parts[-1], value)

        # Save
        config.to_yaml(config.config_file)
        print("Configuration updated")


def cmd_tools(args: argparse.Namespace) -> None:
    """List or test tools"""
    from quokka.tools.base import ToolRegistry
    from quokka.tools.shell_exec import ShellExecTool
    from quokka.tools.file_ops import FileOpsTool
    from quokka.tools.pdf_handler import PDFHandlerTool
    from quokka.tools.web_fetch import WebFetchTool
    from quokka.tools.obsidian import ObsidianReadTool, ObsidianWriteTool

    registry = ToolRegistry()
    registry.register(ShellExecTool)
    registry.register(FileOpsTool)
    registry.register(PDFHandlerTool)
    registry.register(WebFetchTool)
    registry.register(ObsidianReadTool)
    registry.register(ObsidianWriteTool)

    if args.list:
        print("Available tools:")
        for name in registry.list_tools():
            tool_class = registry.get(name)
            if tool_class:
                print(f"\n  {name}:")
                print(f"    {tool_class.description[:80]}...")

    elif args.schema:
        print("Tool schemas (JSON):")
        print(json.dumps(registry.get_openai_schemas(), indent=2))


def cmd_session(args: argparse.Namespace) -> None:
    """Manage sessions"""
    from quokka.memory.session import SessionManager

    manager = SessionManager()

    if args.list:
        print(f"Active sessions: {manager.get_active_count()}")
        for user_id in manager.get_all_user_ids():
            print(f"  User: {user_id}")

    elif args.clear:
        if args.clear == "all":
            for user_id in manager.get_all_user_ids():
                asyncio.run(manager.clear(user_id))
            print("Cleared all sessions")
        else:
            asyncio.run(manager.clear(int(args.clear)))
            print(f"Cleared session for user {args.clear}")


def main() -> None:
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Quokka Agent - Local automation assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize configuration")
    init_parser.add_argument("--config", "-c", default="config/config.yaml", help="Config file path")
    init_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing config")
    init_parser.add_argument("--telegram-token", help="Telegram bot token")
    init_parser.add_argument("--ollama-url", help="Ollama API URL")
    init_parser.add_argument("--ollama-model", help="Ollama model name")
    init_parser.add_argument("--openrouter-key", help="OpenRouter API key")
    init_parser.set_defaults(func=cmd_init)

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the agent")
    run_parser.set_defaults(func=cmd_run)

    # Config command
    config_parser = subparsers.add_parser("config", help="Show or modify configuration")
    config_parser.add_argument("--show", action="store_true", help="Show current config")
    config_parser.add_argument("--set", nargs="+", help="Set config values (key=value)")
    config_parser.set_defaults(func=cmd_config)

    # Tools command
    tools_parser = subparsers.add_parser("tools", help="List or test tools")
    tools_parser.add_argument("--list", action="store_true", help="List available tools")
    tools_parser.add_argument("--schema", action="store_true", help="Show tool schemas")
    tools_parser.set_defaults(func=cmd_tools)

    # Session command
    session_parser = subparsers.add_parser("session", help="Manage sessions")
    session_parser.add_argument("--list", action="store_true", help="List active sessions")
    session_parser.add_argument("--clear", metavar="USER_ID", help="Clear session (use 'all' for all)")
    session_parser.set_defaults(func=cmd_session)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
