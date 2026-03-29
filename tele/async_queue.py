"""Reusable async queue infrastructure with persistence and retry.

This module provides generic persistent queue classes with:
- JSON Lines storage for durability
- Automatic retry with exponential backoff
- Dead-letter queue support
- Async processing with background tasks
- Graceful shutdown
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Generic, TypeVar, List, Callable, Awaitable, Optional, Any

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class QueueItem:
    """Base class for queue items."""
    id: int  # Unique identifier
    retry_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    last_attempt: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    def unique_key(self) -> tuple:
        """Return a tuple that uniquely identifies this item.

        Used for removal from queue to prevent accidentally removing
        related items with the same id/chat_id but different types.

        Default implementation uses (id, chat_id) if chat_id exists,
        otherwise just (id).

        Subclasses can override to include additional fields
        (e.g., InteractionTask includes interaction_type).
        """
        # Check if chat_id attribute exists (subclasses may have it)
        if hasattr(self, 'chat_id') and getattr(self, 'chat_id') is not None:
            return (self.id, getattr(self, 'chat_id'))
        return (self.id,)


class PersistentQueue(Generic[T]):
    """Generic persistent queue with JSON Lines storage.

    Features:
    - Append-only for writes (fast)
    - Atomic rewrite for remove/update (temp file + rename)
    - In-memory cache for reads
    - Auto-recovery from write failures
    - Never raises on I/O errors

    The item_class must be a dataclass that can be constructed from a dict.
    """

    def __init__(self, path: Path, item_class: type):
        """Initialize the persistent queue.

        Args:
            path: Path to the JSON Lines file
            item_class: The dataclass type for items in this queue
        """
        self.path = Path(path)
        self.item_class = item_class
        self._cache: Optional[List[T]] = None

    def _ensure_dir(self) -> bool:
        """Ensure the directory exists.

        Returns:
            True if directory exists or was created, False on failure
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error("Failed to create directory %s: %s", self.path.parent, e)
            return False

    def append(self, item: T) -> bool:
        """Append an item to the queue.

        Args:
            item: The item to append

        Returns:
            True on success, False on failure (never raises)
        """
        if not self._ensure_dir():
            return False

        try:
            # Convert to dict if it's a dataclass
            if hasattr(item, 'to_dict'):
                data = item.to_dict()
            else:
                data = asdict(item) if hasattr(item, '__dataclass_fields__') else item

            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(data) + '\n')

            # Invalidate cache
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to append to %s: %s", self.path, e)
            return False

    def read_all(self) -> List[T]:
        """Read all items from the queue.

        Returns:
            List of items (empty list if file doesn't exist or on error)
        """
        if self._cache is not None:
            return self._cache.copy()

        if not self.path.exists():
            self._cache = []
            return []

        items = []
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            item = self.item_class(**data)
                            items.append(item)
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning("Skipping invalid line in %s: %s", self.path, e)
                            continue
        except Exception as e:
            logger.error("Failed to read %s: %s", self.path, e)

        self._cache = items
        return items.copy()

    def remove(self, ids: List[int]) -> bool:
        """Remove items by ID (rewrite file without them).

        Args:
            ids: List of IDs to remove

        Returns:
            True on success, False on failure (never raises)
        """
        if not ids:
            return True

        if not self.path.exists():
            return True

        try:
            # Read all, filter out removed ones
            remaining = []
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            if data.get('id') not in ids:
                                remaining.append(line)
                        except json.JSONDecodeError:
                            continue

            # Atomic write: write to temp file, then rename
            temp_path = self.path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in remaining:
                    f.write(line + '\n')

            # Atomic rename
            temp_path.replace(self.path)

            # Invalidate cache
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to remove from %s: %s", self.path, e)
            return False

    def remove_by_id_and_chat(self, items: List[tuple]) -> bool:
        """Remove items by (id, chat_id) tuples to prevent cross-chat collision.

        Telegram message_ids are per-chat sequences. Chat A's message_id=100
        and Chat B's message_id=100 are DIFFERENT messages. Using remove(id)
        alone could accidentally delete the wrong item from another chat.

        Args:
            items: List of (id, chat_id) tuples to remove

        Returns:
            True on success, False on failure (never raises)
        """
        if not items:
            return True

        if not self.path.exists():
            return True

        try:
            # Read all, filter out removed ones
            remaining = []
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            item_id = data.get('id')
                            item_chat_id = data.get('chat_id')
                            # Match by (id, chat_id) tuple
                            if (item_id, item_chat_id) not in items:
                                remaining.append(line)
                        except json.JSONDecodeError:
                            continue

            # Atomic write: write to temp file, then rename
            temp_path = self.path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in remaining:
                    f.write(line + '\n')

            # Atomic rename
            temp_path.replace(self.path)

            # Invalidate cache
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to remove by (id, chat_id) from %s: %s", self.path, e)
            return False

    def remove_by_unique_key(self, keys: List[tuple]) -> bool:
        """Remove items by their unique_key tuples.

        This method uses the same unique_key() concept from QueueItem to
        remove only specific items, preventing accidental removal of
        related items with the same (id, chat_id) but different types
        (e.g., received_mark vs result_mark vs reply).

        Args:
            keys: List of unique_key tuples to remove.
                  Format depends on item class:
                  - (id,) for basic QueueItem without chat_id
                  - (id, chat_id) for items with chat_id
                  - (id, chat_id, interaction_type) for InteractionTask

        Returns:
            True on success, False on failure (never raises)
        """
        if not keys:
            return True

        if not self.path.exists():
            return True

        try:
            remaining = []
            removed_count = 0
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            # Build unique_key from data using same logic as QueueItem.unique_key()
                            data_key = (data.get('id'),)
                            if 'chat_id' in data and data.get('chat_id') is not None:
                                data_key = (data.get('id'), data.get('chat_id'))
                            if 'interaction_type' in data:
                                data_key = (data.get('id'), data.get('chat_id'), data.get('interaction_type'))

                            if data_key in keys:
                                removed_count += 1
                            else:
                                remaining.append(line)
                        except json.JSONDecodeError:
                            continue

            if removed_count > 0:
                # Atomic write
                temp_path = self.path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    for line in remaining:
                        f.write(line + '\n')
                temp_path.replace(self.path)
                # Invalidate cache
                self._cache = None

            return True
        except Exception as e:
            logger.error("Failed to remove by unique_key from %s: %s", self.path, e)
            return False

    def update(self, item: T) -> bool:
        """Update an item in the queue (rewrite file).

        Args:
            item: The item to update (matched by id)

        Returns:
            True on success, False on failure (never raises)
        """
        if not self.path.exists():
            return False

        try:
            # Convert to dict
            if hasattr(item, 'to_dict'):
                new_data = item.to_dict()
            else:
                new_data = asdict(item) if hasattr(item, '__dataclass_fields__') else item

            item_id = new_data.get('id')
            if item_id is None:
                return False

            # Read all, update matching one
            lines = []
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            if data.get('id') == item_id:
                                lines.append(json.dumps(new_data))
                            else:
                                lines.append(line)
                        except json.JSONDecodeError:
                            continue

            # Atomic write
            temp_path = self.path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')

            temp_path.replace(self.path)

            # Invalidate cache
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to update %s: %s", self.path, e)
            return False

    def update_by_id_and_chat(self, item: T) -> bool:
        """Update an item in the queue by (id, chat_id) to prevent cross-chat collision.

        Like remove_by_id_and_chat, this prevents updating the wrong item when
        multiple chats have items with the same id.

        Args:
            item: The item to update (matched by id AND chat_id)

        Returns:
            True on success, False on failure (never raises)
        """
        if not self.path.exists():
            return False

        try:
            # Convert to dict
            if hasattr(item, 'to_dict'):
                new_data = item.to_dict()
            else:
                new_data = asdict(item) if hasattr(item, '__dataclass_fields__') else item

            item_id = new_data.get('id')
            item_chat_id = new_data.get('chat_id')
            if item_id is None:
                return False

            # Read all, update matching one by (id, chat_id)
            lines = []
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            # Match by BOTH id AND chat_id
                            if data.get('id') == item_id and data.get('chat_id') == item_chat_id:
                                lines.append(json.dumps(new_data))
                            else:
                                lines.append(line)
                        except json.JSONDecodeError:
                            continue

            # Atomic write
            temp_path = self.path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')

            temp_path.replace(self.path)

            # Invalidate cache
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to update by (id, chat_id) in %s: %s", self.path, e)
            return False

    def update_by_unique_key(self, item: T) -> bool:
        """Update an item in the queue by its unique_key.

        Like remove_by_unique_key, this updates only the specific item
        matching the unique_key, preventing accidental updates to related
        items with the same (id, chat_id) but different types.

        Args:
            item: The item to update (matched by unique_key)

        Returns:
            True on success, False on failure (never raises)
        """
        if not self.path.exists():
            return False

        try:
            # Convert to dict
            if hasattr(item, 'to_dict'):
                new_data = item.to_dict()
            else:
                new_data = asdict(item) if hasattr(item, '__dataclass_fields__') else item

            # Build unique_key from new_data
            new_key = (new_data.get('id'),)
            if 'chat_id' in new_data and new_data.get('chat_id') is not None:
                new_key = (new_data.get('id'), new_data.get('chat_id'))
            if 'interaction_type' in new_data:
                new_key = (new_data.get('id'), new_data.get('chat_id'), new_data.get('interaction_type'))

            # Read all, update matching one by unique_key
            lines = []
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            # Build key for this line
                            data_key = (data.get('id'),)
                            if 'chat_id' in data and data.get('chat_id') is not None:
                                data_key = (data.get('id'), data.get('chat_id'))
                            if 'interaction_type' in data:
                                data_key = (data.get('id'), data.get('chat_id'), data.get('interaction_type'))

                            if data_key == new_key:
                                lines.append(json.dumps(new_data))
                            else:
                                lines.append(line)
                        except json.JSONDecodeError:
                            continue

            # Atomic write
            temp_path = self.path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')

            temp_path.replace(self.path)

            # Invalidate cache
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to update by unique_key in %s: %s", self.path, e)
            return False

    def remove_matching(self, predicate: Callable[[dict], bool]) -> int:
        """Remove items matching a predicate function.

        This is useful for removing items based on multiple fields (e.g.,
        remove received_mark for a specific message when result_mark is queued).

        Args:
            predicate: Function that takes a dict and returns True to remove the item

        Returns:
            Number of items removed (0 if none or on error)
        """
        if not self.path.exists():
            return 0

        try:
            removed_count = 0
            remaining = []
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            if predicate(data):
                                removed_count += 1
                            else:
                                remaining.append(line)
                        except json.JSONDecodeError:
                            continue

            if removed_count > 0:
                # Atomic write
                temp_path = self.path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    for line in remaining:
                        f.write(line + '\n')
                temp_path.replace(self.path)

                # Invalidate cache
                self._cache = None

            return removed_count
        except Exception as e:
            logger.error("Failed to remove matching items from %s: %s", self.path, e)
            return 0

    def clear(self) -> bool:
        """Clear the queue.

        Returns:
            True on success, False on failure
        """
        try:
            if self.path.exists():
                self.path.unlink()
            self._cache = []
            return True
        except Exception as e:
            logger.error("Failed to clear %s: %s", self.path, e)
            return False


class AsyncRetryQueue(Generic[T]):
    """Async queue with automatic retry and dead-letter support.

    Features:
    - Configurable retry delays (exponential backoff)
    - Max retries before dead-letter
    - Background task for processing
    - Graceful shutdown
    - Never crashes on processing errors

    Usage:
        async def process_item(item: MyItem) -> bool:
            # Process the item, return True on success
            ...

        queue = AsyncRetryQueue(
            pending_queue=PersistentQueue(...),
            dead_letter_queue=PersistentQueue(...),
            process_func=process_item,
        )
        await queue.start()
        await queue.enqueue(item)
        # ... later ...
        await queue.stop()
    """

    # Default retry delays: 5s, 15s, 60s, 5min, 15min, 1h
    DEFAULT_RETRY_DELAYS = [5, 15, 60, 300, 900, 3600]
    DEFAULT_MAX_RETRIES = 6  # After 6 retries, item goes to dead-letter

    def __init__(
        self,
        pending_queue: PersistentQueue[T],
        dead_letter_queue: Optional[PersistentQueue[T]] = None,
        process_func: Optional[Callable[[T], Awaitable[bool]]] = None,
        check_interval: float = 60.0,
        retry_delays: Optional[List[float]] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        """Initialize the async retry queue.

        Args:
            pending_queue: PersistentQueue for pending items
            dead_letter_queue: PersistentQueue for dead-letter items (optional)
            process_func: Async function to process items, returns True on success
            check_interval: How often to check for due items (seconds)
            retry_delays: Delays between retries (seconds), defaults to exponential backoff
            max_retries: Maximum retries before dead-letter
        """
        self.pending_queue = pending_queue
        self.dead_letter_queue = dead_letter_queue
        self.process_func = process_func
        self.check_interval = check_interval
        self.retry_delays = retry_delays or self.DEFAULT_RETRY_DELAYS
        self.max_retries = max_retries

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background processing task."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        if self.process_func:
            self._task = asyncio.create_task(self._process_loop())
            logger.info("Started async retry queue: %s", self.pending_queue.path)

    async def stop(self) -> None:
        """Stop the background processing task gracefully."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        logger.info("Stopped async retry queue: %s", self.pending_queue.path)

    async def enqueue(self, item: T) -> bool:
        """Enqueue an item for processing.

        Args:
            item: The item to enqueue

        Returns:
            True if successfully enqueued, False on failure
        """
        success = self.pending_queue.append(item)
        if success:
            logger.debug("Enqueued item %s in %s",
                        getattr(item, 'id', '?'), self.pending_queue.path)
        return success

    def enqueue_sync(self, item: T) -> bool:
        """Synchronously enqueue an item (for use in non-async context).

        Args:
            item: The item to enqueue

        Returns:
            True if successfully enqueued, False on failure
        """
        return self.pending_queue.append(item)

    def get_pending(self) -> List[T]:
        """Get all pending items.

        Returns:
            List of pending items
        """
        return self.pending_queue.read_all()

    def get_dead_letter(self) -> List[T]:
        """Get all dead-letter items.

        Returns:
            List of dead-letter items
        """
        if self.dead_letter_queue:
            return self.dead_letter_queue.read_all()
        return []

    async def _process_loop(self) -> None:
        """Background loop that processes due items."""
        while self._running:
            try:
                await self._process_due_items()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in process loop: %s", e)

            # Wait for next check interval or stop signal
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.check_interval
                )
                # If we get here, stop was requested
                break
            except asyncio.TimeoutError:
                # Normal timeout, continue processing
                pass

    async def _process_due_items(self) -> None:
        """Process all items that are due for retry."""
        items = self.pending_queue.read_all()
        now = datetime.now(timezone.utc)

        for item in items:
            if not self._running:
                break

            # Check if item is due
            if not self._is_due(item, now):
                continue

            # Process the item
            try:
                success = await self.process_func(item)
                if success:
                    self._on_success(item)
                else:
                    self._on_failure(item)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Process function raised exception for item %s: %s",
                           getattr(item, 'id', '?'), e)
                self._on_failure(item)

    def _is_due(self, item: T, now: datetime) -> bool:
        """Check if an item is due for processing.

        An item is due if:
        - It has no last_attempt (never processed)
        - Enough time has passed since last_attempt based on retry_count
        """
        last_attempt = getattr(item, 'last_attempt', None)
        retry_count = getattr(item, 'retry_count', 0)

        if last_attempt is None:
            return True

        try:
            last_time = datetime.fromisoformat(last_attempt.replace('Z', '+00:00'))
            delay = self.retry_delays[min(retry_count, len(self.retry_delays) - 1)]
            due_time = last_time.timestamp() + delay
            return now.timestamp() >= due_time
        except Exception:
            return True

    def _on_success(self, item: T) -> None:
        """Handle successful processing.

        Uses unique_key() to remove only the specific item that succeeded,
        preventing accidental removal of related items with the same
        (id, chat_id) but different types (e.g., received_mark vs result_mark).
        """
        item_id = getattr(item, 'id', '?')
        # Use unique_key() to remove only this specific item
        key = item.unique_key() if hasattr(item, 'unique_key') else (item_id,)
        self.pending_queue.remove_by_unique_key([key])
        logger.debug("Item %s processed successfully, removed from queue", item_id)

    def _on_failure(self, item: T) -> None:
        """Handle failed processing.

        Uses unique_key() to update/remove only the specific item that failed,
        preventing accidental modification of related items with the same
        (id, chat_id) but different types (e.g., received_mark vs result_mark).
        """
        item_id = getattr(item, 'id', '?')
        retry_count = getattr(item, 'retry_count', 0)
        key = item.unique_key() if hasattr(item, 'unique_key') else (item_id,)

        if retry_count >= self.max_retries:
            # Move to dead-letter
            logger.warning("Item %s exceeded max retries (%s), moving to dead-letter",
                         item_id, self.max_retries)
            if self.dead_letter_queue:
                # Update item with failure info before moving
                if hasattr(item, 'retry_count'):
                    item.retry_count = retry_count + 1
                if hasattr(item, 'last_attempt'):
                    item.last_attempt = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                append_success = self.dead_letter_queue.append(item)
                if not append_success:
                    logger.error("Failed to append item %s to dead-letter queue %s! Item may be lost!",
                               item_id, self.dead_letter_queue.path)
            else:
                logger.warning("No dead_letter_queue configured! Item %s will be lost!", item_id)
            # Remove from pending queue using unique_key to remove only this specific item
            remove_success = self.pending_queue.remove_by_unique_key([key])
            if not remove_success:
                logger.warning("Failed to remove item %s from pending queue", item_id)
        else:
            # Update retry count and last_attempt
            if hasattr(item, 'retry_count'):
                item.retry_count = retry_count + 1
            if hasattr(item, 'last_attempt'):
                item.last_attempt = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            # Use update_by_unique_key to update only this specific item
            self.pending_queue.update_by_unique_key(item)
            logger.info("Item %s failed, will retry (attempt %s/%s)",
                       item_id, retry_count + 1, self.max_retries)


def safe_write_json(path: Path, data: dict, description: str = "state") -> bool:
    """Write JSON to file atomically.

    Args:
        path: Path to write to
        data: Data to write
        description: Description for error messages

    Returns:
        True on success, False on failure (never raises)
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        temp_path.replace(path)
        return True
    except Exception as e:
        logger.error("Failed to write %s to %s: %s", description, path, e)
        return False


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Read JSON from file safely.

    Args:
        path: Path to read from
        default: Default value if file doesn't exist or on error

    Returns:
        Parsed JSON data or default value (never raises)
    """
    if not path.exists():
        return default

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to read %s: %s", path, e)
        return default