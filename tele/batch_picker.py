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

    def _parse_timestamp(self, ts: Optional[str]) -> Optional[datetime]:
        """Parse ISO timestamp string to datetime."""
        if ts is None:
            return None
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None

    def calculate_wait_time(
        self,
        ready_messages: List[PendingMessage],
        now: datetime,
    ) -> float:
        """Calculate how long to wait before taking a batch.

        Wait until the newest message has "cooled":
        created_at + debounce_interval <= now

        Returns:
            0.0 if batch is ready to take
            Positive float for seconds to wait
        """
        if not ready_messages:
            return self.check_interval

        # Find the newest message's created_at
        newest_time = None
        for msg in ready_messages:
            created = self._parse_timestamp(msg.created_at)
            if created is not None:
                if newest_time is None or created > newest_time:
                    newest_time = created

        if newest_time is None:
            # No created_at info, assume ready
            return 0.0

        # Calculate when the newest message will be cool
        cool_time = newest_time + timedelta(seconds=self.debounce_interval)

        if cool_time <= now:
            return 0.0

        return (cool_time - now).total_seconds()