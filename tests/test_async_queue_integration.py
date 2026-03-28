"""Tests for AsyncRetryQueue integration behavior.

These tests verify the complete flow of the async retry queue:
- Success: item removed from pending
- Failure: retry count incremented
- Max retries: moved to dead-letter
- Cross-chat collision: items with same id but different chat_id are handled correctly
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock
from datetime import datetime, timezone

import pytest

from tele.tasks import InteractionTask, DeadInteractionTask
from tele.async_queue import PersistentQueue, AsyncRetryQueue


class TestAsyncRetryQueueSuccess:
    """Tests for successful processing behavior."""

    @pytest.mark.asyncio
    async def test_success_removes_from_pending(self, tmp_path):
        """Successfully processed items should be removed from pending queue."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add a task
        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        )
        pending_queue.append(task)

        # Create queue with process_func that always succeeds
        process_func = AsyncMock(return_value=True)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Verify: pending is empty, dead is empty (item was processed successfully)
        assert len(pending_queue.read_all()) == 0
        assert len(dead_queue.read_all()) == 0
        process_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_with_cross_chat_same_id(self, tmp_path):
        """When processing succeeds for one chat, another chat's item with same id should remain."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add two tasks with SAME id but DIFFERENT chat_id
        task_chat_a = InteractionTask(
            id=100,
            chat_id=111,  # Chat A
            interaction_type='received_mark',
            data={'emoji': '👀'},
        )
        task_chat_b = InteractionTask(
            id=100,
            chat_id=222,  # Chat B - different chat
            interaction_type='received_mark',
            data={'emoji': '✅'},
        )
        pending_queue.append(task_chat_a)
        pending_queue.append(task_chat_b)

        # Process function succeeds for Chat A only
        async def process_selective(t):
            return t.chat_id == 111  # Only Chat A succeeds

        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_selective,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Verify: Chat A removed, Chat B remains in pending
        pending_items = pending_queue.read_all()
        assert len(pending_items) == 1
        assert pending_items[0].chat_id == 222  # Chat B remains
        assert len(dead_queue.read_all()) == 0


class TestAsyncRetryQueueFailure:
    """Tests for failure and retry behavior."""

    @pytest.mark.asyncio
    async def test_failure_increments_retry_count(self, tmp_path):
        """Failed processing should increment retry_count."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add a task with retry_count=0
        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=0,
        )
        pending_queue.append(task)

        # Process function that always fails
        process_func = AsyncMock(return_value=False)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Verify: retry_count incremented, still in pending
        pending_items = pending_queue.read_all()
        assert len(pending_items) == 1
        assert pending_items[0].retry_count == 1
        assert len(dead_queue.read_all()) == 0

    @pytest.mark.asyncio
    async def test_max_retries_moves_to_dead_letter(self, tmp_path):
        """Items exceeding max_retries should be moved to dead-letter queue."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add a task already at max retries
        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=3,  # Already at max_retries
        )
        pending_queue.append(task)

        process_func = AsyncMock(return_value=False)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Verify: pending empty, dead-letter has the item
        assert len(pending_queue.read_all()) == 0
        dead_items = dead_queue.read_all()
        assert len(dead_items) == 1
        assert dead_items[0].id == 1
        assert dead_items[0].chat_id == 123

    @pytest.mark.asyncio
    async def test_failure_updates_last_attempt(self, tmp_path):
        """Failed processing should update last_attempt timestamp."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=0,
            last_attempt=None,
        )
        pending_queue.append(task)

        process_func = AsyncMock(return_value=False)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        pending_items = pending_queue.read_all()
        assert pending_items[0].last_attempt is not None


class TestAsyncRetryQueueCrossChatCollision:
    """Tests for cross-chat collision scenarios.

    This is the critical bug that was discovered: Telegram message_ids are
    per-chat sequences, so different chats can have the same message_id.
    """

    @pytest.mark.asyncio
    async def test_failure_does_not_remove_other_chat_same_id(self, tmp_path):
        """When one chat's item fails and moves to dead-letter, another chat's item with same id should remain."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add two tasks with SAME id but DIFFERENT chat_id
        # Chat A: already at max retries, will fail and go to dead-letter
        task_chat_a = InteractionTask(
            id=100,
            chat_id=111,  # Chat A
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=3,  # At max retries
            last_attempt=None,  # Due immediately
        )
        # Chat B: fresh task, should NOT be processed in this round
        # Give it a recent last_attempt so it's NOT due (in backoff period)
        recent_time = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        task_chat_b = InteractionTask(
            id=100,  # SAME id
            chat_id=222,  # Chat B - DIFFERENT
            interaction_type='received_mark',
            data={'emoji': '✅'},
            retry_count=1,  # Has been retried once
            last_attempt=recent_time,  # Recently failed, in backoff
        )
        pending_queue.append(task_chat_a)
        pending_queue.append(task_chat_b)

        process_func = AsyncMock(return_value=False)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
            retry_delays=[5, 15, 60],  # At least 5 seconds before retry
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # CRITICAL: Chat B should still be in pending (not affected by Chat A's failure)
        # Chat B was in backoff period, so it wasn't even processed
        pending_items = pending_queue.read_all()
        assert len(pending_items) == 1, "Chat B's item should remain in pending"
        assert pending_items[0].chat_id == 222, "Remaining item should be from Chat B"
        # Chat B was NOT processed (was in backoff), so retry_count unchanged
        assert pending_items[0].retry_count == 1, "Chat B's retry_count should be unchanged"

        # Chat A should be in dead-letter
        dead_items = dead_queue.read_all()
        assert len(dead_items) == 1
        assert dead_items[0].chat_id == 111, "Dead item should be from Chat A"

    @pytest.mark.asyncio
    async def test_success_does_not_remove_other_chat_same_id(self, tmp_path):
        """When one chat's item succeeds, another chat's item with same id should remain."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add two tasks with SAME id but DIFFERENT chat_id
        task_chat_a = InteractionTask(
            id=100,
            chat_id=111,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        )
        task_chat_b = InteractionTask(
            id=100,  # SAME id
            chat_id=222,  # DIFFERENT chat
            interaction_type='received_mark',
            data={'emoji': '✅'},
        )
        pending_queue.append(task_chat_a)
        pending_queue.append(task_chat_b)

        # Process function succeeds for Chat A only
        async def process_selective(t):
            return t.chat_id == 111

        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_selective,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Chat B should remain in pending
        pending_items = pending_queue.read_all()
        assert len(pending_items) == 1
        assert pending_items[0].chat_id == 222

        # Nothing in dead-letter
        assert len(dead_queue.read_all()) == 0

    @pytest.mark.asyncio
    async def test_multiple_chats_same_ids_tracked_independently(self, tmp_path):
        """Multiple chats with same message_ids should be tracked independently.

        This tests the fix for the cross-chat collision bug in update():
        - Chat A's item fails -> update retry_count
        - Chat B's item with same id should NOT be affected
        """
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add tasks from 3 different chats, all with message_id=1
        for chat_id in [111, 222, 333]:
            pending_queue.append(InteractionTask(
                id=1,  # All have the SAME id
                chat_id=chat_id,
                interaction_type='received_mark',
                data={'emoji': '👀'},
                retry_count=0,
            ))

        # Verify 3 items
        assert len(pending_queue.read_all()) == 3

        # Process function fails for Chat 111 only
        async def process_selective(t):
            return t.chat_id != 111  # Only Chat 111 fails

        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_selective,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Chat 222 and 333 succeeded -> removed from pending
        # Chat 111 failed -> retry_count incremented, stays in pending
        pending_items = pending_queue.read_all()
        assert len(pending_items) == 1, f"Expected 1 item, got {len(pending_items)}"
        assert pending_items[0].chat_id == 111, "Remaining item should be from Chat 111"
        assert pending_items[0].retry_count == 1, "Chat 111's retry_count should be incremented"

        # Nothing in dead-letter (no one exceeded max_retries)
        assert len(dead_queue.read_all()) == 0


class TestAsyncRetryQueueEnqueue:
    """Tests for enqueue behavior."""

    @pytest.mark.asyncio
    async def test_enqueue_adds_to_pending(self, tmp_path):
        """Enqueue should add item to pending queue."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=AsyncMock(return_value=True),
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()

        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        )
        success = await retry_queue.enqueue(task)

        await retry_queue.stop()

        assert success is True
        assert len(pending_queue.read_all()) == 1

    @pytest.mark.asyncio
    async def test_get_pending_returns_current_items(self, tmp_path):
        """get_pending should return all items currently in pending queue."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add items directly to pending
        for i in range(3):
            pending_queue.append(InteractionTask(
                id=i + 1,
                chat_id=123,
                interaction_type='received_mark',
                data={'emoji': '👀'},
            ))

        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=AsyncMock(return_value=True),
            check_interval=0.1,
            max_retries=3,
        )

        pending = retry_queue.get_pending()
        assert len(pending) == 3


class TestAsyncRetryQueueIsDue:
    """Tests for _is_due behavior (when items should be processed)."""

    @pytest.mark.asyncio
    async def test_new_item_is_due_immediately(self, tmp_path):
        """Items with no last_attempt should be due immediately."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            last_attempt=None,  # Never processed
        )
        pending_queue.append(task)

        process_func = AsyncMock(return_value=True)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Should have been processed
        process_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_recently_failed_not_due_yet(self, tmp_path):
        """Items that just failed should not be due until retry delay passes."""
        pending_path = tmp_path / "pending.jsonl"
        dead_path = tmp_path / "dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Item with very recent last_attempt
        recent_time = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            last_attempt=recent_time,
            retry_count=1,
        )
        pending_queue.append(task)

        process_func = AsyncMock(return_value=True)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
            retry_delays=[5, 15, 60],  # At least 5 seconds before retry
        )

        await retry_queue.start()
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Should NOT have been processed (still in backoff)
        process_func.assert_not_called()
        assert len(pending_queue.read_all()) == 1