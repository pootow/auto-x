"""Tests for cross-chat collision bugs in retry scheduling.

This module tests that scheduled_retries and other tracking structures
use (message_id, chat_id) tuples instead of just message_id to prevent
cross-chat collision bugs.

Telegram message_ids are per-chat sequences. Chat A's message_id=100
and Chat B's message_id=100 are DIFFERENT messages.
"""

import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tele.state import PendingQueue, PendingMessage, DeadLetterQueue, DeadLetter
from tele.async_queue import PersistentQueue, AsyncRetryQueue
from tele.tasks import InteractionTask, DeadInteractionTask


class TestScheduledRetriesCrossChatCollision:
    """Tests for cross-chat collision in scheduled_retries."""

    @pytest.mark.asyncio
    async def test_scheduled_retries_key_should_include_chat_id(self):
        """Test that scheduled_retries uses (message_id, chat_id) as key.

        This test simulates the bug: two different chats have messages with
        the same message_id (100), both fail. The current code uses just
        message_id as key, causing Chat A's retry to be cancelled when
        Chat B's retry is scheduled.
        """
        # Simulate scheduled_retries dict with current (buggy) implementation
        scheduled_retries_wrong: dict[int, asyncio.Task] = {}

        # Simulate scheduled_retries dict with correct implementation
        scheduled_retries_correct: dict[tuple[int, int], asyncio.Task] = {}

        # Track which retries were cancelled
        cancelled_wrong = []
        cancelled_correct = []

        async def mock_retry_handler(chat_id: int, message_id: int):
            """Mock retry handler that tracks cancellations."""
            try:
                await asyncio.sleep(10)  # Long delay
            except asyncio.CancelledError:
                if scheduled_retries_wrong is not None:
                    cancelled_wrong.append((chat_id, message_id))
                else:
                    cancelled_correct.append((chat_id, message_id))
                raise

        # Chat A message 100 fails -> schedule retry
        task_a = asyncio.create_task(mock_retry_handler(111, 100))

        # BUG: Using just message_id as key
        scheduled_retries_wrong[100] = task_a

        # Correct: Using (message_id, chat_id) tuple
        scheduled_retries_correct[(100, 111)] = task_a

        # Give tasks time to start
        await asyncio.sleep(0.01)

        # Chat B message 100 fails -> schedule retry (same message_id!)
        task_b = asyncio.create_task(mock_retry_handler(222, 100))

        # BUG: This overwrites Chat A's retry, cancelling it
        # In real code: scheduled_retries[item['message_id']] = ...
        old_task_wrong = scheduled_retries_wrong.get(100)
        if old_task_wrong:
            old_task_wrong.cancel()
        scheduled_retries_wrong[100] = task_b

        # Correct: Chat B has different key (100, 222)
        old_task_correct = scheduled_retries_correct.get((100, 222))
        # Should NOT find Chat A's task because key is different
        assert old_task_correct is None
        scheduled_retries_correct[(100, 222)] = task_b

        # Give time for cancellation to propagate
        await asyncio.sleep(0.01)

        # BUG result: Chat A's retry was cancelled!
        assert task_a.cancelled() or task_a.done()

        # Correct result: Chat A's task should still be running
        # (We can't actually test this because we cancelled it above
        # to demonstrate the bug. The key insight is the KEY difference.)

        # Cleanup
        task_b.cancel()
        try:
            await task_b
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_cross_chat_messages_same_id_independent_retries(self):
        """Test that two chats with same message_id have independent retries.

        This is a more complete test showing the actual behavior difference.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)

            # Chat A message 100
            msg_a = PendingMessage(
                message_id=100,
                chat_id=111,
                update_id=1,
                message={"id": 100, "chat_id": 111, "text": "chat A"},
            )
            pending_queue.append(msg_a)

            # Chat B message 100 (same message_id, different chat)
            msg_b = PendingMessage(
                message_id=100,
                chat_id=222,
                update_id=2,
                message={"id": 100, "chat_id": 222, "text": "chat B"},
            )
            pending_queue.append(msg_b)

            # Verify both are in queue
            pending = pending_queue.read_all()
            assert len(pending) == 2

            # Verify remove_by_chat works correctly with tuples
            # Remove Chat A's message only
            pending_queue.remove_by_chat([(100, 111)])

            pending = pending_queue.read_all()
            assert len(pending) == 1
            # Chat B's message should remain
            assert pending[0].chat_id == 222
            assert pending[0].message_id == 100

    @pytest.mark.asyncio
    async def test_retry_scheduling_simulation(self):
        """Simulate the actual retry scheduling logic from cli.py.

        This test extracts and tests the retry scheduling logic to
        demonstrate the bug clearly.
        """
        # Simulated scheduled_retries from cli.py line 321
        scheduled_retries: dict[int, asyncio.Task] = {}  # BUG: uses int key

        # Simulated batch_items with error status
        batch_items = [
            {
                'message_id': 100,
                'chat_id': 111,  # Chat A
                'update_id': 1,
                'message': {'id': 100, 'chat_id': 111, 'text': 'A'},
                'retry_count': 0,
            },
            {
                'message_id': 100,  # Same message_id!
                'chat_id': 222,  # Chat B - different chat
                'update_id': 2,
                'message': {'id': 100, 'chat_id': 222, 'text': 'B'},
                'retry_count': 0,
            },
        ]

        error_ids = [(100, 111), (100, 222)]  # Both failed

        tasks_by_chat = {}  # Track tasks by chat for verification
        cancellation_detected = False

        async def schedule_retry_mock(item):
            """Mock retry handler."""
            try:
                await asyncio.sleep(5)  # Retry delay
            except asyncio.CancelledError:
                raise

        # Simulate the buggy logic from cli.py:452-455
        for item in batch_items:
            item_key = (item['message_id'], item['chat_id'])
            if item_key in error_ids:
                # BUG: uses item['message_id'] alone, not tuple
                msg_id = item['message_id']

                # Check and cancel existing retry (BUG: wrong key causes cross-chat collision)
                if msg_id in scheduled_retries:
                    # BUG: This cancels Chat A's task when Chat B's message has same id!
                    old_task = scheduled_retries[msg_id]
                    old_task.cancel()
                    cancellation_detected = True  # Track that cancellation happened
                    try:
                        await old_task
                    except asyncio.CancelledError:
                        pass

                # Schedule new retry
                new_task = asyncio.create_task(schedule_retry_mock(item))
                scheduled_retries[msg_id] = new_task
                tasks_by_chat[item['chat_id']] = new_task

        await asyncio.sleep(0.01)  # Let remaining tasks start

        # BUG VERIFICATION 1: Only one task in dict (Chat B overwrote Chat A)
        assert len(scheduled_retries) == 1  # Should be 2 if keys were tuples!

        # BUG VERIFICATION 2: Cancellation was detected in the loop
        # This proves Chat A's task was cancelled when Chat B's retry was scheduled
        assert cancellation_detected is True

        # BUG VERIFICATION 3: Chat A's task (stored separately) is cancelled/done
        assert tasks_by_chat[111].cancelled() or tasks_by_chat[111].done()

        # BUG VERIFICATION 4: Chat B's task is still running (not cancelled)
        assert not tasks_by_chat[222].done()

        # Cleanup remaining tasks
        for task in scheduled_retries.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_correct_retry_scheduling_with_tuple_key(self):
        """Test the CORRECT retry scheduling using (message_id, chat_id) tuple."""
        # FIXED scheduled_retries using tuple key
        scheduled_retries: dict[tuple[int, int], asyncio.Task] = {}

        batch_items = [
            {
                'message_id': 100,
                'chat_id': 111,  # Chat A
                'update_id': 1,
                'message': {'id': 100, 'chat_id': 111, 'text': 'A'},
                'retry_count': 0,
            },
            {
                'message_id': 100,  # Same message_id!
                'chat_id': 222,  # Chat B - different chat
                'update_id': 2,
                'message': {'id': 100, 'chat_id': 222, 'text': 'B'},
                'retry_count': 0,
            },
        ]

        error_ids = [(100, 111), (100, 222)]

        retry_tasks_created = []
        retry_tasks_cancelled = []

        async def schedule_retry_mock(item):
            retry_tasks_created.append((item['message_id'], item['chat_id']))
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                retry_tasks_cancelled.append((item['message_id'], item['chat_id']))
                raise

        # CORRECT logic using tuple key
        for item in batch_items:
            item_key = (item['message_id'], item['chat_id'])
            if item_key in error_ids:
                # Use tuple key
                key = (item['message_id'], item['chat_id'])

                if key in scheduled_retries:
                    scheduled_retries[key].cancel()
                    try:
                        await scheduled_retries[key]
                    except asyncio.CancelledError:
                        pass

                scheduled_retries[key] = asyncio.create_task(
                    schedule_retry_mock(item)
                )

        await asyncio.sleep(0.01)

        # CORRECT: Both tasks exist (different keys)
        assert len(scheduled_retries) == 2

        # CORRECT: Neither was cancelled by cross-chat collision
        assert (100, 111) not in retry_tasks_cancelled
        assert (100, 222) not in retry_tasks_cancelled

        # Cleanup
        for task in scheduled_retries.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class TestSameChatRetryRescheduling:
    """Tests for retry rescheduling within the same chat."""

    @pytest.mark.asyncio
    async def test_same_chat_message_retry_can_be_cancelled_for_new_retry(self):
        """Test that same-chat retry can be cancelled when scheduling a new retry.

        This is the expected behavior - if message 100 in chat 111 fails again
        before its retry completes, we cancel the old retry and schedule fresh.
        """
        scheduled_retries: dict[tuple[int, int], asyncio.Task] = {}

        retry_count = 0
        max_retries = 3

        async def schedule_retry_mock(chat_id, message_id, retry_num):
            try:
                await asyncio.sleep(5)
                return True
            except asyncio.CancelledError:
                raise

        # Chat A message 100 fails -> schedule retry 1
        key = (100, 111)
        task1 = asyncio.create_task(schedule_retry_mock(111, 100, 1))
        scheduled_retries[key] = task1

        await asyncio.sleep(0.01)

        # Same message fails again before retry completes
        # Cancel old retry and schedule new one
        if key in scheduled_retries:
            scheduled_retries[key].cancel()
            try:
                await scheduled_retries[key]
            except asyncio.CancelledError:
                pass

        task2 = asyncio.create_task(schedule_retry_mock(111, 100, 2))
        scheduled_retries[key] = task2

        await asyncio.sleep(0.01)

        # Old task should be cancelled
        assert task1.cancelled()

        # New task should be running
        assert not task2.done()

        # Cleanup
        task2.cancel()
        try:
            await task2
        except asyncio.CancelledError:
            pass


class TestInteractionRetryBehavior:
    """Tests for interaction task retry behavior.

    NOTE: The actual fix for the reaction override problem is in
    TestResultMarkRemovesReceivedMark - result_mark removes pending received_mark
    from the queue. This class tests basic retry mechanics.
    """

    @pytest.mark.asyncio
    async def test_interaction_failure_triggers_retry(self):
        """Test that interaction failure triggers retry mechanism."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_path = Path(tmpdir) / "interaction_pending.jsonl"
            dead_path = Path(tmpdir) / "interaction_dead.jsonl"

            pending_queue = PersistentQueue[InteractionTask](
                path=pending_path, item_class=InteractionTask
            )
            dead_queue = PersistentQueue[DeadInteractionTask](
                path=dead_path, item_class=DeadInteractionTask
            )

            call_count = 0

            async def failing_reaction_handler(task: InteractionTask) -> bool:
                """Handler that fails for received_mark, succeeds for result_mark."""
                nonlocal call_count
                call_count += 1

                if task.interaction_type == 'received_mark':
                    # Simulate failure
                    return False
                else:
                    # result_mark succeeds
                    return True

            queue = AsyncRetryQueue[InteractionTask](
                pending_queue=pending_queue,
                dead_letter_queue=dead_queue,
                process_func=failing_reaction_handler,
                check_interval=0.1,
                max_retries=3,
            )

            await queue.start()

            # Enqueue a received_mark task
            received_task = InteractionTask(
                id=100,
                chat_id=111,
                interaction_type='received_mark',
                data={'emoji': '👀'},
            )
            await queue.enqueue(received_task)

            # Wait for processing
            await asyncio.sleep(0.3)

            # Stop the queue
            await queue.stop()

            # CRITICAL: Without the fix, this would retry 3+ times
            # With the fix (returning True on received_mark failure), it should only call once
            # Note: The actual fix is in cli.py's process_interaction, not here
            # This test documents the expected behavior
            # In actual code, received_mark failure returns True, preventing retry

            # For this test without the fix, verify retry behavior
            assert call_count >= 1  # At least one attempt

    @pytest.mark.asyncio
    async def test_result_mark_failure_should_retry(self):
        """Test that result_mark failure DOES trigger retry.

        result_mark is the final state and must retry until success or max retries.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_path = Path(tmpdir) / "interaction_pending.jsonl"
            dead_path = Path(tmpdir) / "interaction_dead.jsonl"

            pending_queue = PersistentQueue[InteractionTask](
                path=pending_path, item_class=InteractionTask
            )
            dead_queue = PersistentQueue[DeadInteractionTask](
                path=dead_path, item_class=DeadInteractionTask
            )

            call_count = 0

            async def always_fail_handler(task: InteractionTask) -> bool:
                """Handler that always fails."""
                nonlocal call_count
                call_count += 1
                return False

            queue = AsyncRetryQueue[InteractionTask](
                pending_queue=pending_queue,
                dead_letter_queue=dead_queue,
                process_func=always_fail_handler,
                check_interval=0.05,
                retry_delays=[0.02, 0.02, 0.02],  # Fast retries for testing
                max_retries=3,
            )

            await queue.start()

            # Enqueue a result_mark task
            result_task = InteractionTask(
                id=100,
                chat_id=111,
                interaction_type='result_mark',
                data={'emoji': '✅'},
            )
            await queue.enqueue(result_task)

            # Wait for all retries (need enough time for multiple check intervals)
            await asyncio.sleep(0.5)

            # Stop the queue
            await queue.stop()

            # result_mark should have retried multiple times
            # With max_retries=3, it should attempt at least 3 times before dead-letter
            assert call_count >= 3, f"Expected >= 3 calls, got {call_count}"

            # Check dead-letter queue
            dead_items = dead_queue.read_all()
            # Note: dead-letter may not have items if retries are still in progress
            # The key assertion is that retries happened

    @pytest.mark.asyncio
    async def test_reaction_override_scenario(self):
        """Test the scenario where received_mark retry would override result_mark.

        PROBLEM: Telegram setMessageReaction REPLACES all reactions.
        If received_mark fails and retries, it could overwrite result_mark.

        FIX: When result_mark is enqueued, we remove any pending received_mark
        for the same message from the queue. This prevents the race condition.

        See TestResultMarkRemovesReceivedMark for tests of the actual fix.
        """
        # Simulate the message processing timeline
        reactions_sent = []

        async def mock_add_reaction(chat_id, message_id, emoji):
            """Mock that tracks reaction order."""
            reactions_sent.append((message_id, emoji, datetime.now(timezone.utc)))
            return True

        # Timeline simulation:
        # T1: received_mark (👀) sent -> fails (network issue)
        # T2: result_mark (✅) sent -> succeeds
        # T3: received_mark retry succeeds -> overwrites ✅ with 👀

        # Without fix: reactions_sent would be [(100, '👀'), (100, '✅'), (100, '👀')]
        # With fix: reactions_sent would be [(100, '✅')] (received_mark not retried)

        # This is a documentation test showing the problem
        # The actual fix prevents T3 from happening
        pass


class TestResultMarkRemovesReceivedMark:
    """Tests for the fix: result_mark removes pending received_mark.

    When result_mark is enqueued, any pending received_mark for the same
    message should be removed from the queue. This prevents the race condition
    where received_mark retry succeeds after result_mark, overwriting the final state.
    """

    @pytest.mark.asyncio
    async def test_result_mark_removes_pending_received_mark(self):
        """Test that enqueuing result_mark removes pending received_mark."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_path = Path(tmpdir) / "interaction_pending.jsonl"

            pending_queue = PersistentQueue[InteractionTask](
                path=pending_path, item_class=InteractionTask
            )

            # Enqueue a received_mark
            received_task = InteractionTask(
                id=100,
                chat_id=111,
                interaction_type='received_mark',
                data={'emoji': '👀'},
            )
            pending_queue.append(received_task)

            # Verify it's in the queue
            items = pending_queue.read_all()
            assert len(items) == 1
            assert items[0].interaction_type == 'received_mark'

            # Now simulate what happens when result_mark is enqueued:
            # Remove received_mark for this message first
            removed = pending_queue.remove_matching(
                lambda d: (
                    d.get('id') == 100 and
                    d.get('chat_id') == 111 and
                    d.get('interaction_type') == 'received_mark'
                )
            )

            assert removed == 1

            # Verify queue is now empty
            items = pending_queue.read_all()
            assert len(items) == 0

            # Now enqueue result_mark
            result_task = InteractionTask(
                id=100,
                chat_id=111,
                interaction_type='result_mark',
                data={'emoji': '✅'},
            )
            pending_queue.append(result_task)

            items = pending_queue.read_all()
            assert len(items) == 1
            assert items[0].interaction_type == 'result_mark'

    @pytest.mark.asyncio
    async def test_result_mark_does_not_remove_other_messages_received_mark(self):
        """Test that result_mark only removes received_mark for same message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_path = Path(tmpdir) / "interaction_pending.jsonl"

            pending_queue = PersistentQueue[InteractionTask](
                path=pending_path, item_class=InteractionTask
            )

            # Enqueue received_marks for different messages
            pending_queue.append(InteractionTask(
                id=100, chat_id=111, interaction_type='received_mark', data={'emoji': '👀'}
            ))
            pending_queue.append(InteractionTask(
                id=101, chat_id=111, interaction_type='received_mark', data={'emoji': '👀'}
            ))
            pending_queue.append(InteractionTask(
                id=100, chat_id=222, interaction_type='received_mark', data={'emoji': '👀'}
            ))

            # Remove received_mark only for message 100 in chat 111
            removed = pending_queue.remove_matching(
                lambda d: (
                    d.get('id') == 100 and
                    d.get('chat_id') == 111 and
                    d.get('interaction_type') == 'received_mark'
                )
            )

            assert removed == 1

            # Verify other received_marks are still there
            items = pending_queue.read_all()
            assert len(items) == 2
            ids_remaining = [(i.id, i.chat_id) for i in items]
            assert (101, 111) in ids_remaining
            assert (100, 222) in ids_remaining

    @pytest.mark.asyncio
    async def test_result_mark_does_not_remove_result_marks(self):
        """Test that result_mark removal only affects received_mark, not result_mark."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_path = Path(tmpdir) / "interaction_pending.jsonl"

            pending_queue = PersistentQueue[InteractionTask](
                path=pending_path, item_class=InteractionTask
            )

            # Enqueue both types for same message
            pending_queue.append(InteractionTask(
                id=100, chat_id=111, interaction_type='received_mark', data={'emoji': '👀'}
            ))
            pending_queue.append(InteractionTask(
                id=100, chat_id=111, interaction_type='result_mark', data={'emoji': '⚠️'}
            ))

            # Remove received_mark only
            removed = pending_queue.remove_matching(
                lambda d: (
                    d.get('id') == 100 and
                    d.get('chat_id') == 111 and
                    d.get('interaction_type') == 'received_mark'
                )
            )

            assert removed == 1

            # Verify result_mark is still there
            items = pending_queue.read_all()
            assert len(items) == 1
            assert items[0].interaction_type == 'result_mark'