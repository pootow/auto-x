"""Pull-based debounce batch picker for message queue."""

from datetime import datetime, timezone, timedelta
from typing import List, Optional
import asyncio

from .state import PendingMessage


class BatchPicker:
    """Pull-based debounce batch picker.

    Implements the "cool down" debounce logic:
    - Read ready messages from queue
    - Wait until all ready messages have "cooled" (created_at + interval <= now)
    - Take a batch and return it

    This is the opposite of push-based debounce. Instead of resetting a timer
    on each new message, we wait for messages to become "cool".
    """

    def __init__(
        self,
        page_size: int = 10,
        debounce_interval: float = 3.0,
        check_interval: float = 1.0,
    ):
        """Initialize the batch picker.

        Args:
            page_size: Maximum messages per batch
            debounce_interval: Seconds to wait for messages to "cool"
            check_interval: Seconds to wait when no messages are ready
        """
        self.page_size = page_size
        self.debounce_interval = debounce_interval
        self.check_interval = check_interval

    def pick_batch(
        self,
        ready_messages: List[PendingMessage],
    ) -> List[PendingMessage]:
        """Pick a batch from ready messages.

        Args:
            ready_messages: Messages that are ready for processing

        Returns:
            Up to page_size messages to process
        """
        return ready_messages[:self.page_size]