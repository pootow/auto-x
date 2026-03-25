"""Tests for persistence classes (PendingQueue, DeadLetterQueue)."""

import json
import tempfile
from pathlib import Path

import pytest

from tele.state import PendingMessage, PendingQueue, DeadLetter, DeadLetterQueue


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
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))

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
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))
        messages = queue.read_all()
        assert messages == []

    def test_remove_messages(self, tmp_path):
        """Test removing messages by ID."""
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))

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
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))

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
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))

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
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))

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
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))
        assert queue._queue_path() == tmp_path / "bot_123_pending.jsonl"

    def test_handles_corrupted_lines(self, tmp_path):
        """Test handling corrupted JSON lines."""
        queue = PendingQueue(chat_id=123, state_dir=str(tmp_path))

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