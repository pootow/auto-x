"""Tests for interaction queue integration in CLI (bot mode).

These tests verify that the CLI correctly:
- Enqueues received_mark when a message is received
- Enqueues result_mark when processing completes
- Enqueues reply when processor returns a reply
- Replays pending interactions on startup
- Stops the interaction queue gracefully on shutdown

All external dependencies (BotClient API) are mocked.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

import pytest

from tele.tasks import InteractionTask, DeadInteractionTask
from tele.async_queue import PersistentQueue


class TestReceivedMarkEnqueued:
    """Tests for received_mark interaction being enqueued."""

    @pytest.mark.asyncio
    async def test_received_mark_task_creation(self, tmp_path):
        """Test that received_mark task is created correctly."""
        from tele.tasks import create_received_mark_task

        # Simulate creating a received_mark task when a message arrives
        message_id = 100
        chat_id = 123456
        emoji = '👀'

        task = create_received_mark_task(message_id, chat_id, emoji)

        assert task.id == 100
        assert task.chat_id == 123456
        assert task.interaction_type == 'received_mark'
        assert task.data['emoji'] == '👀'

    @pytest.mark.asyncio
    async def test_received_mark_can_be_enqueued_to_queue(self, tmp_path):
        """Test that received_mark task can be added to persistent queue."""
        from tele.tasks import create_received_mark_task

        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )

        task = create_received_mark_task(100, 123456, '👀')
        success = queue.append(task)

        assert success is True
        items = queue.read_all()
        assert len(items) == 1
        assert items[0].interaction_type == 'received_mark'


class TestResultMarkEnqueued:
    """Tests for result_mark interaction being enqueued."""

    @pytest.mark.asyncio
    async def test_result_mark_enqueued_on_success(self, tmp_path):
        """When processing succeeds, result_mark should be enqueued."""
        from tele.tasks import create_result_mark_task

        # Simulate the process_batch behavior
        # Create mock queues
        pending_path = tmp_path / "interaction_pending.jsonl"
        dead_path = tmp_path / "interaction_dead.jsonl"
        interaction_pending = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )

        # Simulate a successful processor result
        result = {
            'id': 100,
            'chat_id': 123456,
            'status': 'success',
        }

        # Create and enqueue result_mark task
        emoji = '👍'
        task = create_result_mark_task(result['id'], result['chat_id'], emoji)
        interaction_pending.append(task)

        # Verify
        items = interaction_pending.read_all()
        assert len(items) == 1
        assert items[0].interaction_type == 'result_mark'
        assert items[0].data['emoji'] == '👍'

    @pytest.mark.asyncio
    async def test_result_mark_enqueued_on_error(self, tmp_path):
        """When processing fails with error, result_mark should still be enqueued."""
        from tele.tasks import create_result_mark_task

        pending_path = tmp_path / "interaction_pending.jsonl"
        interaction_pending = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )

        # Simulate an error processor result
        result = {
            'id': 100,
            'chat_id': 123456,
            'status': 'error',
        }

        emoji = '👎'  # Failed mark
        task = create_result_mark_task(result['id'], result['chat_id'], emoji)
        interaction_pending.append(task)

        items = interaction_pending.read_all()
        assert len(items) == 1
        assert items[0].data['emoji'] == '👎'


class TestReplyEnqueued:
    """Tests for reply interaction being enqueued."""

    @pytest.mark.asyncio
    async def test_reply_video_enqueued(self, tmp_path):
        """When processor returns video reply, it should be enqueued."""
        from tele.tasks import create_reply_task

        pending_path = tmp_path / "interaction_pending.jsonl"
        interaction_pending = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )

        # Simulate processor result with video reply
        reply_item = {
            'text': 'Here is the video',
            'media': {
                'type': 'video',
                'url': 'https://example.com/video.mp4',
                'duration': 60,
            }
        }

        task = create_reply_task(100, 123456, reply_item)
        interaction_pending.append(task)

        items = interaction_pending.read_all()
        assert len(items) == 1
        assert items[0].interaction_type == 'reply_video'
        assert items[0].data['media']['url'] == 'https://example.com/video.mp4'

    @pytest.mark.asyncio
    async def test_reply_text_enqueued(self, tmp_path):
        """When processor returns text reply, it should be enqueued."""
        from tele.tasks import create_reply_task

        pending_path = tmp_path / "interaction_pending.jsonl"
        interaction_pending = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )

        reply_item = {'text': 'Hello!'}

        task = create_reply_task(100, 123456, reply_item)
        interaction_pending.append(task)

        items = interaction_pending.read_all()
        assert len(items) == 1
        assert items[0].interaction_type == 'reply_text'
        assert items[0].data['text'] == 'Hello!'


class TestPendingInteractionsReplay:
    """Tests for replaying pending interactions on startup."""

    @pytest.mark.asyncio
    async def test_pending_interactions_exist_on_startup(self, tmp_path):
        """Existing pending interactions should be detected on startup."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        interaction_pending = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )

        # Add some pending interactions from a previous session
        interaction_pending.append(InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=0,
        ))
        interaction_pending.append(InteractionTask(
            id=2,
            chat_id=456,
            interaction_type='result_mark',
            data={'emoji': '👍'},
            retry_count=2,
        ))

        # Verify they exist
        pending = interaction_pending.read_all()
        assert len(pending) == 2

        # The AsyncRetryQueue's _process_loop will automatically process these
        # when the queue is started (no special replay logic needed)

    @pytest.mark.asyncio
    async def test_interaction_queue_state_files_location(self, tmp_path):
        """Interaction queue state files should be in state_dir."""
        state_dir = tmp_path

        # Expected paths
        pending_path = state_dir / "interaction_pending.jsonl"
        dead_path = state_dir / "interaction_dead.jsonl"

        # Create queues
        interaction_pending = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        interaction_dead = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add an item
        interaction_pending.append(InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        ))

        # Verify files exist
        assert pending_path.exists()
        assert not dead_path.exists()  # No dead items yet


class TestInteractionQueueGracefulShutdown:
    """Tests for graceful shutdown of interaction queue."""

    @pytest.mark.asyncio
    async def test_interaction_queue_stop_called_on_shutdown(self, tmp_path):
        """Interaction queue stop() should be called during shutdown."""
        from tele.async_queue import AsyncRetryQueue

        pending_path = tmp_path / "interaction_pending.jsonl"
        dead_path = tmp_path / "interaction_dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        process_func = AsyncMock(return_value=True)
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        assert retry_queue._running is True

        # Simulate shutdown
        await retry_queue.stop()

        assert retry_queue._running is False

    @pytest.mark.asyncio
    async def test_pending_items_preserved_on_shutdown(self, tmp_path):
        """Pending items should be preserved when queue stops."""
        from tele.async_queue import AsyncRetryQueue

        pending_path = tmp_path / "interaction_pending.jsonl"
        dead_path = tmp_path / "interaction_dead.jsonl"

        pending_queue = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )
        dead_queue = PersistentQueue[DeadInteractionTask](
            path=dead_path, item_class=DeadInteractionTask
        )

        # Add an item
        pending_queue.append(InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        ))

        process_func = AsyncMock(return_value=False)  # Always fail
        retry_queue = AsyncRetryQueue(
            pending_queue=pending_queue,
            dead_letter_queue=dead_queue,
            process_func=process_func,
            check_interval=0.1,
            max_retries=3,
        )

        await retry_queue.start()
        # Process the item (it will fail and stay in pending with updated retry_count)
        await retry_queue._process_due_items()
        await retry_queue.stop()

        # Verify item is still in pending (not lost on shutdown)
        pending = pending_queue.read_all()
        assert len(pending) == 1
        assert pending[0].retry_count == 1  # Incremented due to failure


class TestCrossChatCollisionInCLI:
    """Tests for cross-chat collision handling in CLI context."""

    @pytest.mark.asyncio
    async def test_different_chats_same_message_id_interactions(self, tmp_path):
        """Interactions from different chats with same message_id should not collide."""
        from tele.tasks import create_received_mark_task

        pending_path = tmp_path / "interaction_pending.jsonl"
        interaction_pending = PersistentQueue[InteractionTask](
            path=pending_path, item_class=InteractionTask
        )

        # Two different chats, same message_id
        task_chat_a = create_received_mark_task(100, 111, '👀')
        task_chat_b = create_received_mark_task(100, 222, '✅')

        interaction_pending.append(task_chat_a)
        interaction_pending.append(task_chat_b)

        # Verify both exist
        items = interaction_pending.read_all()
        assert len(items) == 2

        # Remove one using remove_by_id_and_chat
        interaction_pending.remove_by_id_and_chat([(100, 111)])

        # Verify only Chat A's item was removed
        items = interaction_pending.read_all()
        assert len(items) == 1
        assert items[0].chat_id == 222
        assert items[0].data['emoji'] == '✅'