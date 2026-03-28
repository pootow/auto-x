"""Tests for persistence classes (PendingQueue, DeadLetterQueue, FatalQueue)."""

import json
import tempfile
from pathlib import Path

import pytest

from tele.state import PendingMessage, PendingQueue, DeadLetter, DeadLetterQueue, FatalError, FatalQueue
from tele.tasks import InteractionTask, DeadInteractionTask, create_received_mark_task, create_result_mark_task, create_reply_task
from tele.async_queue import PersistentQueue


class TestPendingMessage:
    """Tests for PendingMessage dataclass."""

    def test_create_pending_message(self):
        """Test creating a pending message."""
        msg = PendingMessage(
            message_id=123,
            chat_id=456,
            update_id=789,
            message={"id": 123, "text": "hello"},
            retry_count=0,
            last_attempt=None,
        )
        assert msg.message_id == 123
        assert msg.chat_id == 456
        assert msg.update_id == 789
        assert msg.message == {"id": 123, "text": "hello"}
        assert msg.retry_count == 0
        assert msg.last_attempt is None

    def test_pending_message_defaults(self):
        """Test pending message with defaults."""
        msg = PendingMessage(
            message_id=1,
            chat_id=2,
            update_id=3,
            message={},
        )
        assert msg.retry_count == 0
        assert msg.last_attempt is None


class TestPendingQueue:
    """Tests for PendingQueue."""

    def test_append_and_read(self, tmp_path):
        """Test appending and reading messages."""
        queue = PendingQueue(state_dir=str(tmp_path))

        msg = PendingMessage(
            message_id=1,
            chat_id=123,
            update_id=100,
            message={"id": 1, "text": "test"},
        )
        queue.append(msg)

        messages = queue.read_all()
        assert len(messages) == 1
        assert messages[0].message_id == 1
        assert messages[0].chat_id == 123
        assert messages[0].update_id == 100

    def test_read_empty_queue(self, tmp_path):
        """Test reading from empty queue."""
        queue = PendingQueue(state_dir=str(tmp_path))
        messages = queue.read_all()
        assert messages == []

    def test_remove_messages(self, tmp_path):
        """Test removing messages by ID."""
        queue = PendingQueue(state_dir=str(tmp_path))

        # Add multiple messages
        for i in range(3):
            queue.append(PendingMessage(
                message_id=i + 1,
                chat_id=123,
                update_id=100 + i,
                message={"id": i + 1},
            ))

        # Remove first and third
        queue.remove([1, 3])

        messages = queue.read_all()
        assert len(messages) == 1
        assert messages[0].message_id == 2

    def test_remove_nonexistent(self, tmp_path):
        """Test removing non-existent message IDs."""
        queue = PendingQueue(state_dir=str(tmp_path))

        queue.append(PendingMessage(
            message_id=1,
            chat_id=123,
            update_id=100,
            message={"id": 1},
        ))

        # Remove non-existent ID
        queue.remove([999])

        messages = queue.read_all()
        assert len(messages) == 1

    def test_remove_empty_list(self, tmp_path):
        """Test removing with empty list."""
        queue = PendingQueue(state_dir=str(tmp_path))

        queue.append(PendingMessage(
            message_id=1,
            chat_id=123,
            update_id=100,
            message={"id": 1},
        ))

        queue.remove([])
        messages = queue.read_all()
        assert len(messages) == 1

    def test_update_message(self, tmp_path):
        """Test updating a message in the queue."""
        queue = PendingQueue(state_dir=str(tmp_path))

        msg = PendingMessage(
            message_id=1,
            chat_id=123,
            update_id=100,
            message={"id": 1},
            retry_count=0,
            last_attempt=None,
        )
        queue.append(msg)

        # Update with new retry count
        msg.retry_count = 2
        msg.last_attempt = "2024-01-15T10:00:00Z"
        queue.update(msg)

        messages = queue.read_all()
        assert len(messages) == 1
        assert messages[0].retry_count == 2
        assert messages[0].last_attempt == "2024-01-15T10:00:00Z"

    def test_queue_path(self, tmp_path):
        """Test queue file path is correct."""
        queue = PendingQueue(state_dir=str(tmp_path))
        assert queue._queue_path() == tmp_path / "bot_pending.jsonl"

    def test_handles_corrupted_lines(self, tmp_path):
        """Test handling corrupted JSON lines."""
        queue = PendingQueue(state_dir=str(tmp_path))

        # Write valid and invalid lines
        path = queue._queue_path()
        with open(path, 'w') as f:
            f.write('{"message_id": 1, "chat_id": 123, "update_id": 100, "message": {}}\n')
            f.write('invalid json\n')
            f.write('{"message_id": 2, "chat_id": 123, "update_id": 101, "message": {}}\n')

        messages = queue.read_all()
        assert len(messages) == 2
        assert messages[0].message_id == 1
        assert messages[1].message_id == 2

    def test_remove_uses_chat_id_to_avoid_cross_chat_collision(self, tmp_path):
        """Test that remove uses (message_id, chat_id) tuple to prevent cross-chat collision.

        Telegram message_ids are per-chat sequences. Chat A's message_id=100
        and Chat B's message_id=100 are DIFFERENT messages. If remove only
        uses message_id, it could accidentally delete the wrong message.
        """
        queue = PendingQueue(state_dir=str(tmp_path))  # Global queue

        # Add messages from two different chats with SAME message_id
        # Chat A: message_id=100
        queue.append(PendingMessage(
            message_id=100,
            chat_id=111,  # Chat A
            update_id=1000,
            message={"id": 100, "text": "from chat A"},
        ))
        # Chat B: message_id=100 (same ID, different chat)
        queue.append(PendingMessage(
            message_id=100,
            chat_id=222,  # Chat B
            update_id=1001,
            message={"id": 100, "text": "from chat B"},
        ))

        # Remove Chat A's message (message_id=100, chat_id=111)
        queue.remove_by_chat([(100, 111)])

        messages = queue.read_all()
        # Chat B's message should STILL be there (same message_id, different chat_id)
        assert len(messages) == 1
        assert messages[0].chat_id == 222
        assert messages[0].message["text"] == "from chat B"


class TestDeadLetter:
    """Tests for DeadLetter dataclass."""

    def test_create_dead_letter(self):
        """Test creating a dead letter."""
        dl = DeadLetter(
            message_id=123,
            chat_id=456,
            message={"id": 123, "text": "hello"},
            exec_cmd="processor --arg value",
            failed_at="2024-01-15T10:00:00Z",
            retry_count=3,
            error="Exit code 1",
        )
        assert dl.message_id == 123
        assert dl.exec_cmd == "processor --arg value"
        assert dl.retry_count == 3


class TestDeadLetterQueue:
    """Tests for DeadLetterQueue."""

    def test_append_and_read(self, tmp_path):
        """Test appending and reading dead letters."""
        path = tmp_path / "bot_123_dead.jsonl"
        queue = DeadLetterQueue(str(path))

        dl = DeadLetter(
            message_id=1,
            chat_id=123,
            message={"id": 1},
            exec_cmd="processor",
            failed_at="2024-01-15T10:00:00Z",
            retry_count=3,
            error="Max retries",
        )
        queue.append(dl)

        entries = queue.read_all()
        assert len(entries) == 1
        assert entries[0].message_id == 1
        assert entries[0].exec_cmd == "processor"

    def test_read_empty_queue(self, tmp_path):
        """Test reading from empty queue."""
        path = tmp_path / "bot_123_dead.jsonl"
        queue = DeadLetterQueue(str(path))
        entries = queue.read_all()
        assert entries == []

    def test_remove_entries(self, tmp_path):
        """Test removing entries by message ID."""
        path = tmp_path / "bot_123_dead.jsonl"
        queue = DeadLetterQueue(str(path))

        for i in range(3):
            queue.append(DeadLetter(
                message_id=i + 1,
                chat_id=123,
                message={"id": i + 1},
                exec_cmd="processor",
                failed_at="2024-01-15T10:00:00Z",
                retry_count=3,
                error="Error",
            ))

        queue.remove([1, 3])

        entries = queue.read_all()
        assert len(entries) == 1
        assert entries[0].message_id == 2

    def test_creates_parent_directory(self):
        """Test that parent directory is created."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "subdir" / "dead.jsonl"
            queue = DeadLetterQueue(str(path))

            queue.append(DeadLetter(
                message_id=1,
                chat_id=123,
                message={},
                exec_cmd="processor",
                failed_at="2024-01-15T10:00:00Z",
                retry_count=3,
                error="Error",
            ))

            assert path.exists()


class TestFatalError:
    """Tests for FatalError dataclass."""

    def test_create_fatal_error(self):
        """Test creating a fatal error."""
        fe = FatalError(
            message_id=123,
            chat_id=456,
            message={"id": 123, "text": "hello"},
            exec_cmd="processor --arg value",
            failed_at="2024-01-15T10:00:00Z",
            reason="Resource 404",
        )
        assert fe.message_id == 123
        assert fe.exec_cmd == "processor --arg value"
        assert fe.reason == "Resource 404"


class TestFatalQueue:
    """Tests for FatalQueue."""

    def test_append_and_read(self, tmp_path):
        """Test appending and reading fatal errors."""
        path = tmp_path / "bot_123_fatal.jsonl"
        queue = FatalQueue(str(path))

        fe = FatalError(
            message_id=1,
            chat_id=123,
            message={"id": 1},
            exec_cmd="processor",
            failed_at="2024-01-15T10:00:00Z",
            reason="Resource 404",
        )
        queue.append(fe)

        entries = queue.read_all()
        assert len(entries) == 1
        assert entries[0].message_id == 1
        assert entries[0].reason == "Resource 404"

    def test_read_empty_queue(self, tmp_path):
        """Test reading from empty queue."""
        path = tmp_path / "bot_123_fatal.jsonl"
        queue = FatalQueue(str(path))
        entries = queue.read_all()
        assert entries == []

    def test_creates_parent_directory(self):
        """Test that parent directory is created."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "subdir" / "fatal.jsonl"
            queue = FatalQueue(str(path))

            queue.append(FatalError(
                message_id=1,
                chat_id=123,
                message={},
                exec_cmd="processor",
                failed_at="2024-01-15T10:00:00Z",
                reason="Error",
            ))

            assert path.exists()


class TestInteractionTask:
    """Tests for InteractionTask dataclass."""

    def test_create_received_mark_task(self):
        """Test creating a received_mark interaction task."""
        task = InteractionTask(
            id=123,
            chat_id=456,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        )
        assert task.id == 123
        assert task.chat_id == 456
        assert task.interaction_type == 'received_mark'
        assert task.data['emoji'] == '👀'

    def test_create_result_mark_task(self):
        """Test creating a result_mark interaction task."""
        task = InteractionTask(
            id=123,
            chat_id=456,
            interaction_type='result_mark',
            data={'emoji': '✅'},
        )
        assert task.id == 123
        assert task.interaction_type == 'result_mark'
        assert task.data['emoji'] == '✅'

    def test_create_reply_video_task(self):
        """Test creating a reply_video interaction task."""
        task = InteractionTask(
            id=123,
            chat_id=456,
            interaction_type='reply_video',
            data={
                'text': 'Video caption',
                'media': {
                    'type': 'video',
                    'url': 'https://example.com/video.mp4',
                    'duration': 60,
                    'width': 1920,
                    'height': 1080,
                },
            },
        )
        assert task.id == 123
        assert task.interaction_type == 'reply_video'
        assert task.data['text'] == 'Video caption'
        assert task.data['media']['url'] == 'https://example.com/video.mp4'

    def test_create_reply_text_task(self):
        """Test creating a reply_text interaction task."""
        task = InteractionTask(
            id=123,
            chat_id=456,
            interaction_type='reply_text',
            data={'text': 'Hello!', 'media': None},
        )
        assert task.id == 123
        assert task.interaction_type == 'reply_text'
        assert task.data['text'] == 'Hello!'

    def test_interaction_task_defaults(self):
        """Test interaction task with defaults."""
        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        )
        assert task.retry_count == 0
        assert task.last_attempt is None
        assert task.created_at is not None


class TestInteractionTaskHelpers:
    """Tests for interaction task helper functions."""

    def test_create_received_mark_task_helper(self):
        """Test the create_received_mark_task helper function."""
        task = create_received_mark_task(123, 456, '👀')
        assert task.id == 123
        assert task.chat_id == 456
        assert task.interaction_type == 'received_mark'
        assert task.data['emoji'] == '👀'

    def test_create_result_mark_task_helper(self):
        """Test the create_result_mark_task helper function."""
        task = create_result_mark_task(123, 456, '✅')
        assert task.id == 123
        assert task.chat_id == 456
        assert task.interaction_type == 'result_mark'
        assert task.data['emoji'] == '✅'

    def test_create_reply_task_with_video(self):
        """Test the create_reply_task helper function with video."""
        reply_item = {
            'text': 'Video caption',
            'media': {
                'type': 'video',
                'url': 'https://example.com/video.mp4',
            },
        }
        task = create_reply_task(123, 456, reply_item)
        assert task.id == 123
        assert task.chat_id == 456
        assert task.interaction_type == 'reply_video'
        assert task.data['media']['url'] == 'https://example.com/video.mp4'

    def test_create_reply_task_with_image(self):
        """Test the create_reply_task helper function with image."""
        reply_item = {
            'text': 'Image caption',
            'media': {
                'type': 'image',
                'url': 'https://example.com/image.jpg',
            },
        }
        task = create_reply_task(123, 456, reply_item)
        assert task.id == 123
        assert task.interaction_type == 'reply_photo'
        assert task.data['media']['url'] == 'https://example.com/image.jpg'

    def test_create_reply_task_text_only(self):
        """Test the create_reply_task helper function with text only."""
        reply_item = {'text': 'Hello!'}
        task = create_reply_task(123, 456, reply_item)
        assert task.id == 123
        assert task.chat_id == 456
        assert task.interaction_type == 'reply_text'
        assert task.data['text'] == 'Hello!'


class TestInteractionQueue:
    """Tests for InteractionTask queue with PersistentQueue."""

    def test_append_and_read_interaction(self, tmp_path):
        """Test appending and reading interaction tasks."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='result_mark',
            data={'emoji': '✅'}
        )
        queue.append(task)

        items = queue.read_all()
        assert len(items) == 1
        assert items[0].interaction_type == 'result_mark'
        assert items[0].data['emoji'] == '✅'

    def test_read_empty_queue(self, tmp_path):
        """Test reading from empty queue."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )
        items = queue.read_all()
        assert items == []

    def test_remove_interaction(self, tmp_path):
        """Test removing interaction tasks by ID."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        # Add multiple tasks
        for i in range(3):
            queue.append(InteractionTask(
                id=i + 1,
                chat_id=123,
                interaction_type='received_mark',
                data={'emoji': '👀'}
            ))

        # Remove first and third
        queue.remove([1, 3])

        items = queue.read_all()
        assert len(items) == 1
        assert items[0].id == 2

    def test_update_interaction_retry_count(self, tmp_path):
        """Test updating interaction retry count."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        task = InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=0,
            last_attempt=None,
        )
        queue.append(task)

        # Update retry count
        task.retry_count = 2
        task.last_attempt = "2024-01-15T10:00:00Z"
        queue.update(task)

        items = queue.read_all()
        assert len(items) == 1
        assert items[0].retry_count == 2
        assert items[0].last_attempt == "2024-01-15T10:00:00Z"

    def test_dead_interaction_queue(self, tmp_path):
        """Test dead-letter queue for interactions."""
        dead_path = tmp_path / "interaction_dead.jsonl"
        queue = PersistentQueue[DeadInteractionTask](
            path=dead_path,
            item_class=DeadInteractionTask
        )

        task = DeadInteractionTask(
            id=1,
            chat_id=123,
            interaction_type='result_mark',
            data={'emoji': '✅'},
            error="Network timeout",
            failed_at="2024-01-15T10:00:00Z",
        )
        queue.append(task)

        items = queue.read_all()
        assert len(items) == 1
        assert items[0].interaction_type == 'result_mark'
        assert items[0].error == "Network timeout"

    def test_creates_parent_directory(self):
        """Test that parent directory is created."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "subdir" / "interaction_pending.jsonl"
            queue = PersistentQueue[InteractionTask](
                path=path,
                item_class=InteractionTask
            )

            queue.append(InteractionTask(
                id=1,
                chat_id=123,
                interaction_type='received_mark',
                data={'emoji': '👀'}
            ))

            assert path.exists()

    def test_handles_corrupted_lines(self, tmp_path):
        """Test handling corrupted JSON lines."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        # Write valid and invalid lines
        with open(pending_path, 'w') as f:
            f.write('{"id": 1, "chat_id": 123, "interaction_type": "received_mark", "data": {"emoji": "👀"}}\n')
            f.write('invalid json\n')
            f.write('{"id": 2, "chat_id": 123, "interaction_type": "result_mark", "data": {"emoji": "✅"}}\n')

        items = queue.read_all()
        assert len(items) == 2
        assert items[0].id == 1
        assert items[1].id == 2

    def test_remove_by_id_and_chat_prevents_collision(self, tmp_path):
        """Test that remove_by_id_and_chat prevents cross-chat collision.

        Two items with same id but different chat_id should not be removed together.
        """
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        # Add two items with SAME id but DIFFERENT chat_id
        queue.append(InteractionTask(
            id=100,  # Same id
            chat_id=111,  # Chat A
            interaction_type='received_mark',
            data={'emoji': '👀'}
        ))
        queue.append(InteractionTask(
            id=100,  # Same id
            chat_id=222,  # Chat B - DIFFERENT
            interaction_type='received_mark',
            data={'emoji': '✅'}
        ))

        # Remove only the first one (id=100, chat_id=111)
        queue.remove_by_id_and_chat([(100, 111)])

        items = queue.read_all()
        assert len(items) == 1
        assert items[0].chat_id == 222  # Chat B's item should remain

    def test_remove_by_id_and_chat_multiple(self, tmp_path):
        """Test removing multiple items by (id, chat_id) tuples."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        # Add multiple items
        for chat_id in [111, 222, 333]:
            for msg_id in [1, 2]:
                queue.append(InteractionTask(
                    id=msg_id,
                    chat_id=chat_id,
                    interaction_type='received_mark',
                    data={'emoji': '👀'}
                ))

        # Verify 6 items
        assert len(queue.read_all()) == 6

        # Remove specific items: (1, 111) and (2, 222)
        queue.remove_by_id_and_chat([(1, 111), (2, 222)])

        items = queue.read_all()
        assert len(items) == 4
        remaining_chats = [i.chat_id for i in items]
        remaining_ids = [(i.id, i.chat_id) for i in items]
        assert (1, 111) not in remaining_ids
        assert (2, 222) not in remaining_ids

    def test_update_by_id_and_chat_prevents_collision(self, tmp_path):
        """Test that update_by_id_and_chat prevents cross-chat collision.

        When updating one chat's item, another chat's item with same id should not be affected.
        """
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        # Add two items with SAME id but DIFFERENT chat_id
        queue.append(InteractionTask(
            id=100,  # Same id
            chat_id=111,  # Chat A
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=0,
        ))
        queue.append(InteractionTask(
            id=100,  # Same id
            chat_id=222,  # Chat B - DIFFERENT
            interaction_type='received_mark',
            data={'emoji': '✅'},
            retry_count=0,
        ))

        # Update Chat A's item (increment retry_count)
        task_a_updated = InteractionTask(
            id=100,
            chat_id=111,  # Chat A
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=1,  # Updated
            last_attempt="2024-01-15T10:00:00Z",
        )
        queue.update_by_id_and_chat(task_a_updated)

        items = queue.read_all()
        assert len(items) == 2, "Both items should still exist"

        # Find each item and verify
        chat_a_item = next(i for i in items if i.chat_id == 111)
        chat_b_item = next(i for i in items if i.chat_id == 222)

        assert chat_a_item.retry_count == 1, "Chat A's retry_count should be updated"
        assert chat_b_item.retry_count == 0, "Chat B's retry_count should be unchanged"

    def test_update_by_id_and_chat_nonexistent(self, tmp_path):
        """Test update_by_id_and_chat on non-existent item."""
        pending_path = tmp_path / "interaction_pending.jsonl"
        queue = PersistentQueue[InteractionTask](
            path=pending_path,
            item_class=InteractionTask
        )

        # Add one item
        queue.append(InteractionTask(
            id=1,
            chat_id=123,
            interaction_type='received_mark',
            data={'emoji': '👀'},
        ))

        # Try to update a non-existent (id, chat_id) combination
        task_nonexistent = InteractionTask(
            id=999,
            chat_id=999,
            interaction_type='received_mark',
            data={'emoji': '👀'},
            retry_count=5,
        )
        queue.update_by_id_and_chat(task_nonexistent)

        # Original item should be unchanged
        items = queue.read_all()
        assert len(items) == 1
        assert items[0].id == 1
        assert items[0].retry_count == 0