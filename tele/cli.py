"""CLI entry point for tele tool."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional, List

import click

from .client import TeleClient
from .config import load_config
from .filter import create_filter, MessageFilter
from .state import StateManager, BotStateManager
from .output import format_message, parse_message_id
from .bot_client import BotClient
from .batch_picker import BatchPicker
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
    """Run bot mode daemon loop with resilience.

    The daemon NEVER crashes - all errors are handled gracefully:
    - Network errors: logged, retry after backoff
    - Processor errors: messages queued for retry
    - Disk errors: logged, in-memory state preserved
    - Interaction errors: queued for retry

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
    from .tasks import (
        MessageTask, InteractionTask, DeadMessageTask, DeadInteractionTask,
        create_received_mark_task, create_result_mark_task, create_reply_task
    )
    from .async_queue import PersistentQueue, AsyncRetryQueue
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

    client = BotClient(
        config.telegram.bot_token,
        config.telegram.bot_api_endpoint,
        endpoint_routing=config.telegram.endpoint_routing
    )
    state_mgr = BotStateManager()
    msg_filter = create_filter(filter_expr) if filter_expr else None

    # Get state directory
    state_dir = Path(state_mgr.state_dir)

    # Initialize persistence for messages (global queue - bot offset is not per-chat)
    pending_queue = PendingQueue()
    dead_letter_path = str(state_dir / "bot_dead.jsonl")
    dead_letter_queue = DeadLetterQueue(dead_letter_path)
    fatal_path = str(state_dir / "bot_fatal.jsonl")
    fatal_queue = FatalQueue(fatal_path)

    # Initialize persistence for interactions (reactions, replies)
    interaction_pending_path = state_dir / "interaction_pending.jsonl"
    interaction_dead_path = state_dir / "interaction_dead.jsonl"
    interaction_pending = PersistentQueue[InteractionTask](
        path=interaction_pending_path,
        item_class=InteractionTask
    )
    interaction_dead = PersistentQueue[DeadInteractionTask](
        path=interaction_dead_path,
        item_class=DeadInteractionTask
    )

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 15, 45]  # seconds

    async def process_interaction(task: InteractionTask) -> bool:
        """Process an interaction task (reaction or reply).

        Args:
            task: InteractionTask to process

        Returns:
            True on success, False on failure
        """
        try:
            if task.interaction_type == 'received_mark' or task.interaction_type == 'result_mark':
                success = await client.add_reaction(task.chat_id, task.id, task.data['emoji'])
                return success
            elif task.interaction_type == 'reply_video':
                media = task.data.get('media', {})
                result = await client.send_video(
                    task.chat_id,
                    media.get('url', ''),
                    caption=task.data.get('text'),
                    reply_to_message_id=task.id,
                    cover=media.get('cover'),
                    duration=media.get('duration'),
                    width=media.get('width'),
                    height=media.get('height')
                )
                return bool(result)
            elif task.interaction_type == 'reply_photo':
                media = task.data.get('media', {})
                result = await client.send_photo(
                    task.chat_id,
                    media.get('url', ''),
                    caption=task.data.get('text'),
                    reply_to_message_id=task.id
                )
                return bool(result)
            elif task.interaction_type == 'reply_text':
                result = await client.send_message(
                    task.chat_id,
                    task.data.get('text', ''),
                    reply_to_message_id=task.id
                )
                return bool(result)
            else:
                logger.warning("Unknown interaction_type: %s", task.interaction_type)
                return False
        except Exception as e:
            logger.error("Error processing interaction %s: %s", task.id, e)
            return False

    # Create interaction queue with retry support
    interaction_queue = AsyncRetryQueue[InteractionTask](
        pending_queue=interaction_pending,
        dead_letter_queue=interaction_dead,
        process_func=process_interaction,
        check_interval=10.0,
        max_retries=6,
    )

    # Start the interaction queue background processing
    await interaction_queue.start()

    # Check for pending interactions from previous session
    pending_interactions = interaction_pending.read_all()
    if pending_interactions:
        logger.info("Replaying %s pending interactions from previous session", len(pending_interactions))

    batch_picker = BatchPicker(
        page_size=page_size,
        debounce_interval=interval,
    )

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
            pending_queue.remove_by_chat([(pmsg.message_id, pmsg.chat_id)])
            return

        delay = RETRY_DELAYS[retry_count] if retry_count < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
        logger.info("Scheduling retry %s for message %s in %ss", retry_count + 1, pmsg.message_id, delay)

        # Use new schedule_retry method - sets ready_at for future processing
        pending_queue.schedule_retry(
            pmsg.message_id,
            pmsg.chat_id,
            backoff_seconds=delay
        )

    async def process_batch(batch_items: List[dict]) -> None:
        """Process a batch of messages through exec command.

        This function NEVER crashes - all errors are handled gracefully.
        """
        # Extract just the messages for the processor
        messages = [item['message'] for item in batch_items]

        # run_exec_command NEVER raises - it returns error status on failure
        results = await run_exec_command(exec_cmd, messages, shell=True)

        # Track (message_id, chat_id) tuples by status
        success_ids = []  # List of (message_id, chat_id)
        error_ids = []   # Retriable errors - List of (message_id, chat_id)
        fatal_ids = []   # Non-retriable - List of (message_id, chat_id)
        fatal_reasons = {}  # (message_id, chat_id) -> reason for fatal errors
        fatal_results = {}  # (message_id, chat_id) -> full result object for logging

        # Mark messages based on status
        for result in results:
            msg_id = result.get('id')
            result_chat_id = result.get('chat_id')
            status = result.get('status')

            # Skip if missing required fields
            if not msg_id or not result_chat_id or not status:
                logger.warning("Skipping result: missing id/chat_id/status: %s", result)
                continue

            # Key for tracking (message_id, chat_id) tuple
            msg_key = (msg_id, result_chat_id)

            # Determine emoji based on status
            if status == 'success':
                emoji = reaction
                success_ids.append(msg_key)
            elif status == 'fatal':
                emoji = failed_mark
                fatal_ids.append(msg_key)
                fatal_reasons[msg_key] = result.get('reason', 'Processor returned fatal status')
                fatal_results[msg_key] = result  # Store full result for detailed logging
            else:  # 'error' or unknown - treat as retriable
                emoji = failed_mark
                error_ids.append(msg_key)

            # Add reaction via interaction queue (with persistence and retry)
            # CRITICAL: Remove any pending received_mark for this message first!
            # Telegram setMessageReaction REPLACES all reactions. If received_mark
            # is still pending when result_mark succeeds, received_mark could later
            # overwrite the final result emoji.
            interaction_pending.remove_matching(
                lambda d: (
                    d.get('id') == msg_id and
                    d.get('chat_id') == result_chat_id and
                    d.get('interaction_type') == 'received_mark'
                )
            )
            task = create_result_mark_task(msg_id, result_chat_id, emoji)
            await interaction_queue.enqueue(task)

            # Handle rich reply from processor via interaction queue
            if status == 'success' and 'reply' in result and result['reply']:
                for r in result['reply']:
                    task = create_reply_task(msg_id, result_chat_id, r)
                    await interaction_queue.enqueue(task)
                    logger.debug("Queued reply for message %s", msg_id)

        # Find messages that had no result at all (processor didn't return them)
        # These should be treated as retriable errors
        result_ids = {
            (r.get('id'), r.get('chat_id'))
            for r in results
            if r.get('id') and r.get('chat_id')
        }
        missing_ids = []
        for item in batch_items:
            item_key = (item['message_id'], item['chat_id'])
            if item_key not in result_ids:
                missing_ids.append(item_key)

        if missing_ids:
            logger.warning("%s messages had no processor result, scheduling retry", len(missing_ids))
            for item in batch_items:
                item_key = (item['message_id'], item['chat_id'])
                if item_key in missing_ids:
                    pmsg = PendingMessage(
                        message_id=item['message_id'],
                        chat_id=item['chat_id'],
                        update_id=item['update_id'],
                        message=item['message'],
                        retry_count=item.get('retry_count', 0),
                        last_attempt=item.get('last_attempt'),
                    )
                    await schedule_retry(pmsg)

        # Handle fatal errors - append to fatal.jsonl
        if fatal_ids:
            # Create fatal_logs directory for detailed error logs
            fatal_logs_dir = state_dir / "fatal_logs"
            fatal_logs_dir.mkdir(parents=True, exist_ok=True)

            for item in batch_items:
                item_key = (item['message_id'], item['chat_id'])
                if item_key in fatal_ids:
                    # Generate log filename: [chat_id]-[message_id]-[timestamp].log
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                    log_filename = f"{item['chat_id']}-{item['message_id']}-{timestamp}-processor-output.log"
                    log_path = fatal_logs_dir / log_filename

                    # Get full result and reason
                    result = fatal_results.get(item_key, {})
                    reason = fatal_reasons.get(item_key, 'Processor returned fatal status')

                    # Write detailed log file
                    try:
                        with open(log_path, 'w', encoding='utf-8') as f:
                            f.write(f"Fatal Error Log\n")
                            f.write(f"===============\n\n")
                            f.write(f"Chat ID: {item['chat_id']}\n")
                            f.write(f"Message ID: {item['message_id']}\n")
                            f.write(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
                            f.write(f"Processor Command: {exec_cmd}\n\n")
                            f.write(f"Reason: {reason}\n\n")
                            f.write(f"Full Processor Result:\n")
                            f.write(json.dumps(result, indent=2, ensure_ascii=False))
                            f.write("\n\n")
                            f.write(f"Original Message:\n")
                            f.write(json.dumps(item['message'], indent=2, ensure_ascii=False))
                            f.write("\n")
                    except Exception as e:
                        logger.error("Failed to write fatal log file: %s", e)

                    fe = FatalError(
                        message_id=item['message_id'],
                        chat_id=item['chat_id'],
                        message=item['message'],
                        exec_cmd=exec_cmd,
                        failed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                        reason=f"{reason}, see {log_filename}",
                        log_file=str(log_path),
                    )
                    fatal_queue.append(fe)
                    logger.warning("Message %s marked as fatal, log: %s", item['message_id'], log_filename)

        # Remove successful and fatal messages from pending
        to_remove = success_ids + fatal_ids
        if to_remove:
            pending_queue.remove_by_chat(to_remove)
            logger.debug("Removed %s messages from pending queue", len(to_remove))

        # Handle error status - schedule retry
        if error_ids:
            for item in batch_items:
                item_key = (item['message_id'], item['chat_id'])
                if item_key in error_ids:
                    pmsg = PendingMessage(
                        message_id=item['message_id'],
                        chat_id=item['chat_id'],
                        update_id=item['update_id'],
                        message=item['message'],
                        retry_count=item.get('retry_count', 0),
                        last_attempt=item.get('last_attempt'),
                    )
                    await schedule_retry(pmsg)

        # Update offset based on max update_id from batch
        if batch_items:
            max_update_id = max(item['update_id'] for item in batch_items if item.get('update_id'))
            state_mgr.save(max_update_id)
            logger.debug("Updated offset to %s", max_update_id)

    async def batch_loop():
        """Background task that picks batches and processes them."""
        while True:
            try:
                batch = await batch_picker.pick_batch_ready(pending_queue)
                if not batch:
                    continue
                # Convert to batch_items format expected by process_batch
                batch_items = [{
                    'message_id': msg.message_id,
                    'chat_id': msg.chat_id,
                    'update_id': msg.update_id,
                    'message': msg.message,
                    'retry_count': msg.retry_count,
                    'last_attempt': msg.last_attempt,
                } for msg in batch]
                await process_batch(batch_items)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in batch loop: %s", e, exc_info=True)
                await asyncio.sleep(1.0)  # Backoff on error

    batch_task = asyncio.create_task(batch_loop())

    # Load last offset
    state = state_mgr.load()
    offset = state.get('last_update_id', 0)

    # Check for pending messages from previous session (will be picked up by batch_loop)
    pending_messages = pending_queue.read_ready()
    if pending_messages:
        logger.info("Replaying %s pending messages from previous session", len(pending_messages))

    # Polling backoff for error recovery
    poll_backoff = 0.0

    try:
        if chat_filter:
            logger.info("Bot mode started, monitoring chat %s...", chat_filter)
        else:
            logger.info("Bot mode started, monitoring all chats...")

        while True:
            try:
                # poll_updates NEVER raises - returns [] on failure
                updates = await client.poll_updates(offset=offset + 1)
                poll_backoff = 0.0  # Reset on success

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

                    # Append to pending file - will be picked up by batch_loop
                    pending_queue.append(pmsg)
                    logger.debug("Queued message %s for processing", msg_id)

                    # Add received reaction via interaction queue (with persistence and retry)
                    if received_mark:
                        task = create_received_mark_task(msg_id, msg_chat_id, received_mark)
                        await interaction_queue.enqueue(task)

                    # NOTE: Do NOT save offset here - offset is saved only after successful processing

            except KeyboardInterrupt:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Unexpected error in main loop - log and continue with backoff
                poll_backoff = min(poll_backoff * 2 or 5.0, 300.0)  # Max 5 minutes
                logger.error("Polling error (retry in %.1fs): %s", poll_backoff, e, exc_info=True)
                await asyncio.sleep(poll_backoff)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        # Stop batch loop task
        batch_task.cancel()
        try:
            await batch_task
        except asyncio.CancelledError:
            pass
        # Stop interaction queue gracefully
        await interaction_queue.stop()
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

    client = BotClient(
        config.telegram.bot_token,
        config.telegram.bot_api_endpoint,
        endpoint_routing=config.telegram.endpoint_routing
    )

    try:
        success_ids = []

        for entry in entries:
            # Use provided exec_cmd or fall back to stored one
            cmd = exec_cmd or entry.exec_cmd
            if not cmd:
                logger.warning("No command for message %s, skipping", entry.message_id)
                continue

            # run_exec_command NEVER raises - returns error status on failure
            results = await run_exec_command(cmd, [entry.message], shell=True)

            for result in results:
                msg_id = result.get('id')
                result_chat_id = result.get('chat_id')
                status = result.get('status')

                if not msg_id or not result_chat_id or not status:
                    logger.warning("Skipping result: missing id/chat_id/status")
                    continue

                emoji = reaction if status == 'success' else failed_mark
                # add_reaction NEVER raises - returns False on failure
                success = await client.add_reaction(result_chat_id, msg_id, emoji)

                if status == 'success' and success:
                    success_ids.append(entry.message_id)
                    logger.info("Successfully retried message %s", msg_id)
                elif status == 'success':
                    logger.warning("Message %s processed but reaction failed", msg_id)
                else:
                    logger.warning("Message %s still failed after retry", msg_id)

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