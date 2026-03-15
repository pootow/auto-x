"""CLI entry point for tele tool."""

import asyncio
import json
import os
import sys
from typing import Optional, List

import click

from .client import TeleClient
from .config import load_config
from .filter import create_filter, MessageFilter
from .state import StateManager, BotStateManager
from .output import format_message, parse_message_id
from .bot_client import BotClient
from .batcher import MessageBatcher
from .executor import run_exec_command
from .log import setup_logging, get_logger, get_log_level_name, DATAFLOW


@click.command(context_settings={
    'ignore_unknown_options': True,
    'allow_extra_args': True,
    'allow_interspersed_args': False,  # Stop parsing after first positional
})
@click.option('--bot', 'bot_mode', is_flag=True, help='Use Bot API mode (daemon)')
@click.option('--chat', '-c', 'chat_name', help='Chat name or ID')
@click.option('--search', '-s', help='Search query (app mode only)')
@click.option('--filter', '-f', 'filter_expr', help='DSL filter expression')
@click.option('--full', is_flag=True, help='Full processing (ignore incremental state)')
@click.option('--mark', 'mark_mode', is_flag=True, help='Mark mode (read message IDs from stdin)')
@click.option('--reaction', '-r', default='👍', help='Reaction emoji for marking (default: 👍)')
@click.option('--failed-mark', default='👎', help='Failed reaction emoji (bot mode)')
@click.option('--config', 'config_path', help='Path to config file')
@click.option('--batch-size', '-b', default=100, help='Batch size for fetching messages')
@click.option('--limit', '-l', type=int, help='Maximum number of messages to fetch')
@click.option('--page-size', default=10, help='Messages per batch (bot mode)')
@click.option('--interval', default=3.0, help='Debounce interval in seconds (bot mode)')
@click.option('--exec', 'exec_cmd', help='Command to process messages (bot mode)')
@click.option('-v', '--verbose', count=True, help='Increase verbosity (-v, -vv, -vvv, -vvvv)')
@click.pass_context
def cli(
    ctx: click.Context,
    bot_mode: bool,
    chat_name: Optional[str],
    search: Optional[str],
    filter_expr: Optional[str],
    full: bool,
    mark_mode: bool,
    reaction: str,
    failed_mark: str,
    config_path: Optional[str],
    batch_size: int,
    limit: Optional[int],
    page_size: int,
    interval: float,
    exec_cmd: Optional[str],
    verbose: int,
) -> None:
    """Telegram message processing pipeline tool.

    Examples:
        # App mode - Get new messages from a chat
        tele --chat "chat_name"

        # App mode - Search messages
        tele --chat "chat_name" --search "keywords"

        # App mode - Filter messages
        tele --chat "chat_name" --filter 'contains("test")'

        # App mode - Mark messages (read from stdin)
        tele --mark --reaction "👍"

        # Bot mode - Daemon with processor
        tele --bot --chat 12345 --exec "my-processor"

        # Bot mode - Use -- to pass command with args (avoids quoting)
        tele --bot -- python processor.py --arg value

        # Pipeline (app mode)
        tele --chat "chat_name" | processor | tele --mark
    """
    # Setup logging based on verbosity
    logger = setup_logging(verbose)

    # Set TELE_LOG_LEVEL for subprocess (processors)
    os.environ['TELE_LOG_LEVEL'] = get_log_level_name(verbose)

    # Load config
    config = load_config(config_path)

    # Handle -- separator for bot mode (extra args become the exec command)
    extra_args = ctx.args if ctx.args else []

    # Bot mode
    if bot_mode:
        # Use extra args as exec command if provided via --
        if extra_args and not exec_cmd:
            exec_cmd = ' '.join(extra_args)
        elif extra_args and exec_cmd:
            # Both --exec and extra args - append them
            exec_cmd = f"{exec_cmd} {' '.join(extra_args)}"

        if not exec_cmd:
            raise click.UsageError("--bot mode requires --exec <command> or use -- <command>")

        asyncio.run(run_bot_mode(
            config=config,
            chat_name=chat_name,
            filter_expr=filter_expr,
            reaction=reaction,
            failed_mark=failed_mark,
            page_size=page_size,
            interval=interval,
            exec_cmd=exec_cmd,
            verbose=verbose,
        ))
        return

    # Mark mode
    if mark_mode:
        asyncio.run(run_mark_mode(
            config=config,
            reaction=reaction,
        ))
        return

    # Get messages mode
    if chat_name is None:
        chat_name = config.defaults.chat

    if chat_name is None:
        raise click.UsageError("Chat name or ID is required (use --chat or set default in config)")

    asyncio.run(run_get_messages(
        config=config,
        chat_name=chat_name,
        search=search,
        filter_expr=filter_expr,
        full=full,
        batch_size=batch_size,
        limit=limit,
    ))


async def run_bot_mode(
    config,
    chat_name: Optional[str],
    filter_expr: Optional[str],
    reaction: str,
    failed_mark: str,
    page_size: int,
    interval: float,
    exec_cmd: str,
    verbose: int = 0,
) -> None:
    """Run bot mode daemon loop.

    Args:
        config: Configuration
        chat_name: Optional chat ID filter (if None, process all chats)
        filter_expr: Optional DSL filter expression
        reaction: Success reaction emoji
        failed_mark: Failure reaction emoji
        page_size: Messages per batch
        interval: Debounce interval
        exec_cmd: Command to process messages
        verbose: Verbosity level
    """
    logger = get_logger("tele.bot")
    if not config.telegram.bot_token:
        raise click.ClickException("TELEGRAM_BOT_TOKEN required for bot mode")

    # Parse chat ID if specified (optional filter)
    chat_filter = None
    if chat_name:
        try:
            chat_filter = int(chat_name.lstrip('@'))
        except ValueError:
            raise click.ClickException("Chat must be numeric ID in bot mode")

    client = BotClient(config.telegram.bot_token)
    state_mgr = BotStateManager()
    msg_filter = create_filter(filter_expr) if filter_expr else None

    batcher = MessageBatcher(page_size=page_size, interval=interval)

    async def process_batch(messages: List[dict]) -> None:
        """Process a batch of messages through exec command."""
        try:
            results = await run_exec_command(exec_cmd, messages, shell=True)

            # Mark messages based on status
            for result in results:
                msg_id = result.get('id')
                result_chat_id = result.get('chat_id')
                status = result.get('status')

                # Skip if missing required fields
                if not msg_id or not result_chat_id or not status:
                    logger.warning("Skipping result: missing id/chat_id/status: %s", result)
                    continue

                emoji = reaction if status == 'success' else failed_mark
                try:
                    await client.add_reaction(result_chat_id, msg_id, emoji)
                    logger.debug("Marked message %s in chat %s with %s", msg_id, result_chat_id, emoji)
                except Exception as e:
                    logger.error("Failed to mark message %s in chat %s: %s", msg_id, result_chat_id, e)

            # Update offset on success
            if results:
                # Get max update_id from the original updates
                # Note: We need to track update_id separately
                pass

        except Exception as e:
            logger.error("Batch processing failed: %s", e)

    batcher.on_batch = process_batch

    # Load last offset (use 0 if no chat filter, meaning process all)
    state_key = chat_filter if chat_filter else 0
    state = state_mgr.load(state_key)
    offset = state.get('last_update_id', 0)

    # Track update_ids for state updates
    pending_updates: dict = {}

    try:
        if chat_filter:
            logger.info("Bot mode started, monitoring chat %s...", chat_filter)
        else:
            logger.info("Bot mode started, monitoring all chats...")
        while True:
            updates = await client.poll_updates(offset=offset + 1)

            for update in updates:
                update_id = update.get('update_id')
                offset = update_id

                # Extract message from update
                message = update.get('message') or update.get('channel_post')
                if not message:
                    continue

                # Filter chat if specified
                msg_chat_id = message.get('chat', {}).get('id')
                if chat_filter and msg_chat_id != chat_filter:
                    continue

                # Apply filter
                if msg_filter and not msg_filter.matches(message):
                    continue

                # Format message (no status in input)
                formatted = format_message(message)
                pending_updates[message.get('message_id')] = update_id

                # Add to batcher
                import json
                await batcher.add(json.loads(formatted))
                logger.debug("Queued message %s for processing", message.get('message_id'))

                # Save state after each update
                state_mgr.save(state_key, update_id)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await batcher.flush_remaining()
    finally:
        await client.close()


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
    logger = get_logger("tele.app")
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
        logger.debug("Connecting to Telegram...")
        await client.connect()
        logger.info("Connected to Telegram")

        # Resolve chat
        try:
            chat_id = await client.get_chat_id(chat_name)
            logger.debug("Resolved chat '%s' to ID %s", chat_name, chat_id)
        except ValueError as e:
            logger.error("Could not resolve chat: %s", e)
            sys.exit(1)

        # Determine min_id for incremental processing
        min_id = None
        if not full and search is None:
            state = state_manager.load(chat_id)
            min_id = state.last_message_id if state.last_message_id > 0 else None
            if min_id:
                logger.debug("Resuming from message ID %s", min_id)

        # Fetch messages
        max_id = None  # Will be set after fetching for state update
        message_count = 0
        last_id = 0

        if search:
            logger.debug("Searching for '%s'", search)
            # Search mode - no incremental optimization
            async for message in client.iter_search_messages(
                chat_name, search, limit=limit
            ):
                if msg_filter and not msg_filter.matches(message):
                    continue
                output = format_message(message, chat_id)
                logger.log(DATAFLOW, ">>> %s", output)
                print(output)
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
                output = format_message(message, chat_id)
                logger.log(DATAFLOW, ">>> %s", output)
                print(output)
                message_count += 1
                if message.id > last_id:
                    last_id = message.id

        logger.debug("Processed %s messages", message_count)

        # Update state if we processed messages
        if not full and last_id > 0:
            state_manager.update(chat_id, last_id)
            logger.debug("Updated state to message ID %s", last_id)

    except Exception as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    finally:
        logger.debug("Disconnecting from Telegram...")
        await client.disconnect()


async def run_mark_mode(config, reaction: str) -> None:
    """Run the mark mode.

    Reads message IDs and chat IDs from stdin and adds reactions.

    Args:
        config: Configuration
        reaction: Emoji to use for reaction
    """
    logger = get_logger("tele.mark")
    # Initialize client
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
        session_name=config.telegram.session_name,
    )

    try:
        logger.debug("Connecting to Telegram...")
        await client.connect()
        logger.info("Connected to Telegram")

        # Read from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            logger.log(DATAFLOW, "<<< %s", line)

            try:
                message_id, chat_id = parse_message_id(line)
                await client.add_reaction(chat_id, message_id, reaction)
                logger.debug("Added reaction %s to message %s in chat %s", reaction, message_id, chat_id)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON line: %s", line)
            except Exception as e:
                logger.error("Error processing line: %s", e)

    except Exception as e:
        logger.error("Error: %s", e)
        sys.exit(1)
    finally:
        logger.debug("Disconnecting from Telegram...")
        await client.disconnect()


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()