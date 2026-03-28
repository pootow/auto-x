import pytest
from datetime import datetime, timezone, timedelta
from tele.batch_picker import BatchPicker
from tele.state import PendingMessage


class TestBatchPicker:
    """Tests for pull-based debounce batch picker."""

    def test_batch_picker_initialization(self):
        """BatchPicker should initialize with given parameters."""
        picker = BatchPicker(page_size=10, debounce_interval=3.0)
        assert picker.page_size == 10
        assert picker.debounce_interval == 3.0

    def test_batch_picker_defaults(self):
        """BatchPicker should have sensible defaults."""
        picker = BatchPicker()
        assert picker.page_size == 10
        assert picker.debounce_interval == 3.0

    def test_calculate_wait_time_returns_zero_when_all_cool(self):
        """When all messages are cool, wait time should be 0."""
        picker = BatchPicker(debounce_interval=3.0)

        now = datetime.now(timezone.utc)

        # Messages created 5 seconds ago (2 seconds past debounce)
        created_at = (now - timedelta(seconds=5)).isoformat().replace('+00:00', 'Z')

        messages = [
            PendingMessage(
                message_id=1, chat_id=123, update_id=100,
                message={"id": 1}, created_at=created_at
            )
        ]

        wait_time = picker.calculate_wait_time(messages, now)
        assert wait_time == 0.0

    def test_calculate_wait_time_returns_positive_when_still_warm(self):
        """When messages are still warm, return time to wait."""
        picker = BatchPicker(debounce_interval=3.0)

        now = datetime.now(timezone.utc)

        # Message created 1 second ago (needs 2 more seconds to cool)
        created_at = (now - timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')

        messages = [
            PendingMessage(
                message_id=1, chat_id=123, update_id=100,
                message={"id": 1}, created_at=created_at
            )
        ]

        wait_time = picker.calculate_wait_time(messages, now)
        assert 1.9 < wait_time < 2.1  # Approximately 2 seconds

    def test_calculate_wait_time_with_multiple_messages(self):
        """Wait for the newest message to cool."""
        picker = BatchPicker(debounce_interval=3.0)

        now = datetime.now(timezone.utc)

        # Old message - already cool
        old_created = (now - timedelta(seconds=10)).isoformat().replace('+00:00', 'Z')
        # New message - needs 1 more second
        new_created = (now - timedelta(seconds=2)).isoformat().replace('+00:00', 'Z')

        messages = [
            PendingMessage(
                message_id=1, chat_id=123, update_id=100,
                message={"id": 1}, created_at=old_created
            ),
            PendingMessage(
                message_id=2, chat_id=123, update_id=101,
                message={"id": 2}, created_at=new_created
            ),
        ]

        wait_time = picker.calculate_wait_time(messages, now)
        assert 0.9 < wait_time < 1.1  # Wait for newest to cool

    @pytest.mark.asyncio
    async def test_pick_batch_ready_returns_immediately_when_cool(self, tmp_path):
        """When messages are cool, should return batch immediately."""
        from tele.state import PendingQueue

        picker = BatchPicker(page_size=10, debounce_interval=0.1)
        queue = PendingQueue(state_dir=str(tmp_path))

        now = datetime.now(timezone.utc)
        created_at = (now - timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')

        queue.append(PendingMessage(
            message_id=1, chat_id=123, update_id=100,
            message={"id": 1}, created_at=created_at
        ))

        batch = await picker.pick_batch_ready(queue)
        assert len(batch) == 1
        assert batch[0].message_id == 1

    @pytest.mark.asyncio
    async def test_pick_batch_ready_waits_for_debounce(self, tmp_path):
        """Should wait for debounce before returning batch."""
        from tele.state import PendingQueue
        import time

        picker = BatchPicker(page_size=10, debounce_interval=0.2)
        queue = PendingQueue(state_dir=str(tmp_path))

        now = datetime.now(timezone.utc)
        # Message just created, needs to wait
        created_at = now.isoformat().replace('+00:00', 'Z')

        queue.append(PendingMessage(
            message_id=1, chat_id=123, update_id=100,
            message={"id": 1}, created_at=created_at
        ))

        start = time.time()
        batch = await picker.pick_batch_ready(queue)
        elapsed = time.time() - start

        assert len(batch) == 1
        assert elapsed >= 0.15  # Should have waited for debounce