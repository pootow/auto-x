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
@click.option('--received-mark', default='👀', help='Reaction when message received (bot mode)')
@click.option('--config', 'config_path', help='Path to config file')
@click.option('--batch-size', '-b', default=100, help='Batch size for fetching messages')
@click.option('--limit', '-l', type=int, help='Maximum number of messages to fetch')
@click.option('--page-size', default=10, help='Messages per batch (bot mode)')
@click.option('--interval', default=3.0, help='Debounce interval in seconds (bot mode)')
@click.option('--exec', 'exec_cmd', help='Command to process messages (bot mode)')
@click.option('--retry-dead', 'retry_dead', help='Retry dead-letter file (path to .jsonl)')
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
    received_mark: str,
    config_path: Optional[str],
    batch_size: int,
    limit: Optional[int],
    page_size: int,
    interval: float,
    exec_cmd: Optional[str],
    retry_dead: Optional[str],
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
            received_mark=received_mark,
            page_size=page_size,
            interval=interval,
            exec_cmd=exec_cmd,
            verbose=verbose,
        ))
        return

    # Retry dead-letter mode
    if retry_dead:
        # Use extra args as exec command if provided via --
        if extra_args and not exec_cmd:
            exec_cmd = ' '.join(extra_args)
        elif extra_args and exec_cmd:
            exec_cmd = f"{exec_cmd} {' '.join(extra_args)}"

        asyncio.run(run_retry_dead(
            dead_letter_path=retry_dead,
            exec_cmd=exec_cmd,
            reaction=reaction,
            failed_mark=failed_mark,
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
    received_mark: str,
    page_size: int,
    interval: float,
    exec_cmd: str,
    verbose: int = 0,
) -> None:
    """Run bot mode daemon loop with persistence and retry.

    Args:
        config: Configuration
        chat_name: Optional chat ID filter (if None, process all chats)
        filter_expr: Optional DSL filter expression
        reaction: Success reaction emoji
        failed_mark: Failure reaction emoji
        received_mark: Reaction when message is received
        page_size: Messages per batch
        interval: Debounce interval
        exec_cmd: Command to process messages
        verbose: Verbosity level
    """
    from .state import PendingQueue, PendingMessage, DeadLetterQueue, DeadLetter, FatalQueue, FatalError
    from datetime import datetime, timezone

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

    # State key for pending/offset files
    state_key = chat_filter if chat_filter else 0

    # Initialize persistence
    pending_queue = PendingQueue(state_key)
    dead_letter_path = str(pending_queue._queue_path()).replace('_pending.jsonl', '_dead.jsonl')
    dead_letter_queue = DeadLetterQueue(dead_letter_path)
    fatal_path = str(pending_queue._queue_path()).replace('_pending.jsonl', '_fatal.jsonl')
    fatal_queue = FatalQueue(fatal_path)

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 15, 45]  # seconds

    batcher = MessageBatcher(page_size=page_size, interval=interval)

    # Track scheduled retries
    scheduled_retries: dict[int, asyncio.Task] = {}

    async def schedule_retry(pmsg: PendingMessage) -> None:
        """Schedule a retry with exponential backoff."""
        retry_count = pmsg.retry_count
        if retry_count >= MAX_RETRIES:
            # Move to dead-letter queue
            logger.warning("Message %s failed after %s retries, moving to dead-letter", pmsg.message_id, MAX_RETRIES)
            dl = DeadLetter(
                message_id=pmsg.message_id,
                chat_id=pmsg.chat_id,
                message=pmsg.message,
                exec_cmd=exec_cmd,
                failed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                retry_count=retry_count,
                error="Max retries exceeded",
            )
            dead_letter_queue.append(dl)
            pending_queue.remove([pmsg.message_id])
            return

        delay = RETRY_DELAYS[retry_count] if retry_count < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
        logger.info("Scheduling retry %s for message %s in %ss", retry_count + 1, pmsg.message_id, delay)

        await asyncio.sleep(delay)

        # Update retry count and last_attempt
        pmsg.retry_count = retry_count + 1
        pmsg.last_attempt = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        pending_queue.update(pmsg)

        # Add back to batcher
        await batcher.add({
            'message_id': pmsg.message_id,
            'chat_id': pmsg.chat_id,
            'update_id': pmsg.update_id,
            'message': pmsg.message,
            'retry_count': pmsg.retry_count,
            'last_attempt': pmsg.last_attempt,
        })

    async def process_batch(batch_items: List[dict]) -> None:
        """Process a batch of messages through exec command."""
        # Extract just the messages for the processor
        messages = [item['message'] for item in batch_items]

        try:
            results = await run_exec_command(exec_cmd, messages, shell=True)

            # Track message IDs by status
            success_ids = []
            error_ids = []   # Retriable errors - will be handled by exception path
            fatal_ids = []   # Non-retriable, no value in reprocessing
            fatal_reasons = {}  # message_id -> reason for fatal errors

            # Mark messages based on status
            for result in results:
                msg_id = result.get('id')
                result_chat_id = result.get('chat_id')
                status = result.get('status')

                # Skip if missing required fields
                if not msg_id or not result_chat_id or not status:
                    logger.warning("Skipping result: missing id/chat_id/status: %s", result)
                    continue

                # Determine emoji based on status
                if status == 'success':
                    emoji = reaction
                    success_ids.append(msg_id)
                elif status == 'fatal':
                    emoji = failed_mark
                    fatal_ids.append(msg_id)
                    fatal_reasons[msg_id] = result.get('reason', 'Processor returned fatal status')
                else:  # 'error' or unknown - treat as retriable
                    emoji = failed_mark
                    error_ids.append(msg_id)

                try:
                    await client.add_reaction(result_chat_id, msg_id, emoji)
                    logger.debug("Marked message %s in chat %s with %s", msg_id, result_chat_id, emoji)
                except Exception as e:
                    logger.error("Failed to mark message %s in chat %s: %s", msg_id, result_chat_id, e)

                # Handle rich reply from processor
                if status == 'success' and 'reply' in result and result['reply']:
                    for r in result['reply']:
                        text = r.get('text', '')
                        media = r.get('media')
                        try:
                            if media:
                                if media.get('type') == 'video':
                                    await client.send_video(result_chat_id, media['url'], caption=text, reply_to_message_id=msg_id)
                                    logger.debug("Sent video reply to message %s", msg_id)
                                elif media.get('type') == 'image':
                                    await client.send_photo(result_chat_id, media['url'], caption=text, reply_to_message_id=msg_id)
                                    logger.debug("Sent photo reply to message %s", msg_id)
                            elif text:
                                # Text-only reply - send as text message
                                await client._call_api("sendMessage", {
                                    "chat_id": result_chat_id,
                                    "text": text,
                                    "parse_mode": "MarkdownV2",
                                    "reply_to_message_id": msg_id
                                })
                                logger.debug("Sent text reply to message %s", msg_id)
                        except Exception as e:
                            logger.error("Failed to send reply for message %s: %s", msg_id, e)

            # Handle fatal errors - append to fatal.jsonl
            if fatal_ids:
                for item in batch_items:
                    if item['message_id'] in fatal_ids:
                        fe = FatalError(
                            message_id=item['message_id'],
                            chat_id=item['chat_id'],
                            message=item['message'],
                            exec_cmd=exec_cmd,
                            failed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                            reason=fatal_reasons.get(item['message_id'], 'Processor returned fatal status'),
                        )
                        fatal_queue.append(fe)
                        logger.warning("Message %s marked as fatal, no retry value", item['message_id'])

            # Remove successful and fatal messages from pending
            to_remove = success_ids + fatal_ids
            if to_remove:
                pending_queue.remove(to_remove)
                logger.debug("Removed %s messages from pending queue", len(to_remove))

            # Handle error status - schedule retry
            if error_ids:
                for item in batch_items:
                    if item['message_id'] in error_ids:
                        pmsg = PendingMessage(
                            message_id=item['message_id'],
                            chat_id=item['chat_id'],
                            update_id=item['update_id'],
                            message=item['message'],
                            retry_count=item.get('retry_count', 0),
                            last_attempt=item.get('last_attempt'),
                        )
                        # Cancel any existing retry task
                        if item['message_id'] in scheduled_retries:
                            scheduled_retries[item['message_id']].cancel()
                        # Schedule new retry
                        scheduled_retries[item['message_id']] = asyncio.create_task(schedule_retry(pmsg))

            # Update offset based on max update_id from batch
            if batch_items:
                max_update_id = max(item['update_id'] for item in batch_items if item.get('update_id'))
                state_mgr.save(state_key, max_update_id)
                logger.debug("Updated offset to %s", max_update_id)

        except Exception as e:
            logger.error("Batch processing failed: %s", e)

            # Schedule retries for all messages in batch (processor crashed)
            for item in batch_items:
                pmsg = PendingMessage(
                    message_id=item['message_id'],
                    chat_id=item['chat_id'],
                    update_id=item['update_id'],
                    message=item['message'],
                    retry_count=item.get('retry_count', 0),
                    last_attempt=item.get('last_attempt'),
                )
                # Cancel any existing retry task
                if item['message_id'] in scheduled_retries:
                    scheduled_retries[item['message_id']].cancel()
                # Schedule new retry
                scheduled_retries[item['message_id']] = asyncio.create_task(schedule_retry(pmsg))

    batcher.on_batch = process_batch

    # Load last offset
    state = state_mgr.load(state_key)
    offset = state.get('last_update_id', 0)

    # Load and replay pending messages on startup
    pending_messages = pending_queue.read_all()
    if pending_messages:
        logger.info("Replaying %s pending messages from previous session", len(pending_messages))
        for pmsg in pending_messages:
            await batcher.add({
                'message_id': pmsg.message_id,
                'chat_id': pmsg.chat_id,
                'update_id': pmsg.update_id,
                'message': pmsg.message,
                'retry_count': pmsg.retry_count,
                'last_attempt': pmsg.last_attempt,
            })

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

                msg_id = message.get('message_id')

                # Create pending message
                formatted = json.loads(format_message(message))
                pmsg = PendingMessage(
                    message_id=msg_id,
                    chat_id=msg_chat_id,
                    update_id=update_id,
                    message=formatted,
                    retry_count=0,
                    last_attempt=None,
                )

                # Append to pending file BEFORE adding to batcher
                pending_queue.append(pmsg)

                # Add to batcher with metadata
                await batcher.add({
                    'message_id': pmsg.message_id,
                    'chat_id': pmsg.chat_id,
                    'update_id': pmsg.update_id,
                    'message': pmsg.message,
                    'retry_count': pmsg.retry_count,
                    'last_attempt': pmsg.last_attempt,
                })
                logger.debug("Queued message %s for processing", msg_id)

                # Add received reaction
                if received_mark:
                    try:
                        await client.add_reaction(msg_chat_id, msg_id, received_mark)
                        logger.debug("Added received mark to message %s", msg_id)
                    except Exception as e:
                        logger.warning("Failed to add received mark: %s", e)

                # NOTE: Do NOT save offset here - offset is saved only after successful processing

    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await batcher.flush_remaining()
    finally:
        # Cancel any pending retry tasks
        for task in scheduled_retries.values():
            task.cancel()
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


async def run_retry_dead(
    dead_letter_path: str,
    exec_cmd: Optional[str],
    reaction: str,
    failed_mark: str,
) -> None:
    """Retry dead-letter messages.

    Args:
        dead_letter_path: Path to dead-letter JSONL file
        exec_cmd: Command to process messages (uses stored command if not provided)
        reaction: Success reaction emoji
        failed_mark: Failure reaction emoji
    """
    from .state import DeadLetterQueue
    from .bot_client import BotClient
    from .config import load_config

    logger = get_logger("tele.retry")
    config = load_config()

    if not config.telegram.bot_token:
        raise click.ClickException("TELEGRAM_BOT_TOKEN required for retry-dead mode")

    dead_queue = DeadLetterQueue(dead_letter_path)
    entries = dead_queue.read_all()

    if not entries:
        logger.info("No dead-letter entries found in %s", dead_letter_path)
        return

    logger.info("Found %s dead-letter entries", len(entries))

    client = BotClient(config.telegram.bot_token)

    try:
        success_ids = []

        for entry in entries:
            # Use provided exec_cmd or fall back to stored one
            cmd = exec_cmd or entry.exec_cmd
            if not cmd:
                logger.warning("No command for message %s, skipping", entry.message_id)
                continue

            try:
                results = await run_exec_command(cmd, [entry.message], shell=True)

                for result in results:
                    msg_id = result.get('id')
                    result_chat_id = result.get('chat_id')
                    status = result.get('status')

                    if not msg_id or not result_chat_id or not status:
                        logger.warning("Skipping result: missing id/chat_id/status")
                        continue

                    emoji = reaction if status == 'success' else failed_mark
                    await client.add_reaction(result_chat_id, msg_id, emoji)

                    if status == 'success':
                        success_ids.append(entry.message_id)
                        logger.info("Successfully retried message %s", msg_id)
                    else:
                        logger.warning("Message %s still failed after retry", msg_id)

            except Exception as e:
                logger.error("Retry failed for message %s: %s", entry.message_id, e)

        # Remove successful retries from dead-letter file
        if success_ids:
            dead_queue.remove(success_ids)
            logger.info("Removed %s successful entries from dead-letter file", len(success_ids))

    finally:
        await client.close()


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()