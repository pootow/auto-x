"""CLI entry point for tele tool."""

import asyncio
import json
import sys
from typing import Optional

import click

from .client import TeleClient
from .config import load_config
from .filter import create_filter, MessageFilter
from .state import StateManager
from .output import format_message, parse_message_id


@click.group(invoke_without_command=True)
@click.option('--chat', '-c', 'chat_name', help='Chat name or ID')
@click.option('--search', '-s', help='Search query')
@click.option('--filter', '-f', 'filter_expr', help='DSL filter expression')
@click.option('--full', is_flag=True, help='Full processing (ignore incremental state)')
@click.option('--mark', is_flag=True, help='Mark mode (read message IDs from stdin)')
@click.option('--reaction', '-r', default='✅', help='Reaction emoji for marking (default: ✅)')
@click.option('--config', 'config_path', help='Path to config file')
@click.option('--batch-size', '-b', default=100, help='Batch size for fetching messages')
@click.option('--limit', '-l', type=int, help='Maximum number of messages to fetch')
@click.pass_context
def cli(
    ctx: click.Context,
    chat_name: Optional[str],
    search: Optional[str],
    filter_expr: Optional[str],
    full: bool,
    mark: bool,
    reaction: str,
    config_path: Optional[str],
    batch_size: int,
    limit: Optional[int],
) -> None:
    """Telegram message processing pipeline tool.

    Examples:
        # Get new messages from a chat
        tele --chat "chat_name"

        # Search messages
        tele --chat "chat_name" --search "keywords"

        # Filter messages
        tele --chat "chat_name" --filter 'contains("test") && !has_reaction("✅")'

        # Mark messages (read from stdin)
        tele --mark --reaction "✅"

        # Pipeline
        tele --chat "chat_name" --filter 'contains("important")' | process-message | tele --mark
    """
    ctx.ensure_object(dict)

    # Load config
    config = load_config(config_path)
    ctx.obj['config'] = config

    # Apply defaults
    if chat_name is None:
        chat_name = config.defaults.chat

    if mark:
        # Mark mode - read from stdin
        ctx.obj['mark'] = True
        ctx.obj['reaction'] = reaction
        return

    # Get messages mode
    if chat_name is None:
        raise click.UsageError("Chat name or ID is required (use --chat or set default in config)")

    ctx.obj['chat_name'] = chat_name
    ctx.obj['search'] = search
    ctx.obj['filter_expr'] = filter_expr
    ctx.obj['full'] = full
    ctx.obj['batch_size'] = batch_size
    ctx.obj['limit'] = limit
    ctx.obj['reaction'] = reaction


@cli.result_callback()
@click.pass_context
def process(ctx: click.Context, result, **kwargs) -> None:
    """Process the command."""
    if ctx.obj.get('mark'):
        # Mark mode
        asyncio.run(run_mark_mode(
            config=ctx.obj['config'],
            reaction=ctx.obj['reaction'],
        ))
    elif 'chat_name' in ctx.obj:
        # Get messages mode
        asyncio.run(run_get_messages(
            config=ctx.obj['config'],
            chat_name=ctx.obj['chat_name'],
            search=ctx.obj.get('search'),
            filter_expr=ctx.obj.get('filter_expr'),
            full=ctx.obj.get('full', False),
            batch_size=ctx.obj.get('batch_size', 100),
            limit=ctx.obj.get('limit'),
        ))


async def run_get_messages(
    config,
    chat_name: str,
    search: Optional[str],
    filter_expr: Optional[str],
    full: bool,
    batch_size: int,
    limit: Optional[int],
) -> None:
    """Run the get messages mode.

    Args:
        config: Configuration
        chat_name: Chat name or ID
        search: Optional search query
        filter_expr: Optional DSL filter expression
        full: If True, ignore incremental state
        batch_size: Batch size for fetching
        limit: Maximum messages to fetch
    """
    # Initialize client
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
        session_name=config.telegram.session_name,
    )

    # Create filter if provided
    msg_filter = create_filter(filter_expr) if filter_expr else None

    # State manager
    state_manager = StateManager()

    try:
        await client.connect()

        # Resolve chat
        try:
            chat_id = await client.get_chat_id(chat_name)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        # Determine min_id for incremental processing
        min_id = None
        if not full and search is None:
            state = state_manager.load(chat_id)
            min_id = state.last_message_id if state.last_message_id > 0 else None

        # Fetch messages
        max_id = None  # Will be set after fetching for state update
        message_count = 0
        last_id = 0

        if search:
            # Search mode - no incremental optimization
            async for message in client.iter_search_messages(
                chat_name, search, limit=limit
            ):
                if msg_filter and not msg_filter.matches(message):
                    continue
                print(format_message(message, chat_id))
                message_count += 1
                if message.id > last_id:
                    last_id = message.id
        else:
            # Normal mode - support incremental
            async for message in client.iter_messages(
                chat_name,
                min_id=min_id,
                limit=limit,
                reverse=True,
            ):
                if msg_filter and not msg_filter.matches(message):
                    continue
                print(format_message(message, chat_id))
                message_count += 1
                if message.id > last_id:
                    last_id = message.id

        # Update state if we processed messages
        if not full and last_id > 0:
            state_manager.update(chat_id, last_id)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.disconnect()


async def run_mark_mode(config, reaction: str) -> None:
    """Run the mark mode.

    Reads message IDs and chat IDs from stdin and adds reactions.

    Args:
        config: Configuration
        reaction: Emoji to use for reaction
    """
    # Initialize client
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
        session_name=config.telegram.session_name,
    )

    try:
        await client.connect()

        # Read from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                message_id, chat_id = parse_message_id(line)
                await client.add_reaction(chat_id, message_id, reaction)
            except json.JSONDecodeError:
                print(f"Error: Invalid JSON line: {line}", file=sys.stderr)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await client.disconnect()


def main() -> None:
    """Main entry point."""
    cli(obj={})


if __name__ == '__main__':
    main()