"""Message batching utility for bot mode."""

import asyncio
from typing import List, Callable, Any, Optional


class MessageBatcher:
    """Accumulates messages and flushes on page_size or debounce interval."""

    def __init__(self, page_size: int = 10, interval: float = 3.0):
        """Initialize batcher.

        Args:
            page_size: Max messages per batch
            interval: Debounce interval in seconds
        """
        self.page_size = page_size
        self.interval = interval
        self._messages: List[Any] = []
        self._flush_task: Optional[asyncio.Task] = None
        self.on_batch: Optional[Callable] = None

    async def add(self, message: Any) -> None:
        """Add a message to the batch.

        Triggers flush if page_size reached, otherwise schedules debounce flush.
        """
        self._messages.append(message)

        # Cancel pending flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush immediately if page_size reached
        if len(self._messages) >= self.page_size:
            await self._flush()
        else:
            # Schedule debounce flush
            self._flush_task = asyncio.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        """Wait for interval, then flush if still pending."""
        await asyncio.sleep(self.interval)
        if self._messages:
            await self._flush()

    async def _flush(self) -> None:
        """Flush accumulated messages to callback."""
        if not self._messages:
            return

        batch = self._messages[:]
        self._messages = []

        if self.on_batch:
            await self.on_batch(batch)

    async def flush_remaining(self) -> None:
        """Flush any remaining messages (for shutdown)."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()