"""Tests for persistence classes (PendingQueue, DeadLetterQueue, FatalQueue)."""

import json
import tempfile
from pathlib import Path

import pytest

from tele.state import PendingMessage, PendingQueue, DeadLetter, DeadLetterQueue, FatalError, FatalQueue


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