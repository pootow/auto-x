"""Acceptance tests for state file format contract.

Contract: State file format stability.
"""

import pytest
import json
import tempfile
import os
from datetime import datetime, timezone

from tele.state import (
    StateManager, ChatState,
    BotStateManager,
    PendingQueue, PendingMessage,
    DeadLetterQueue, DeadLetter,
    FatalQueue, FatalError
)


class TestStateFileContract:
    """Contract: State file format stability."""

    def test_bot_state_file_format(self, tmp_path):
        """
        Given: Daemon saves bot state
        When: State file is written
        Then: File is valid JSON
        And: Contains "last_update_id" field (integer)
        """
        state_mgr = BotStateManager(str(tmp_path))
        state_mgr.save(update_id=456)

        # Read the file directly
        state_file = tmp_path / "bot.json"
        assert state_file.exists()

        with open(state_file, 'r') as f:
            data = json.load(f)

        assert "last_update_id" in data
        assert data["last_update_id"] == 456
        assert isinstance(data["last_update_id"], int)
        assert "last_processed_at" in data
        assert isinstance(data["last_processed_at"], str)

    def test_pending_queue_file_format(self, tmp_path):
        """
        Given: Messages are added to pending queue
        When: File is written
        Then: Each line is valid JSON
        And: Each line contains: message_id, chat_id, update_id, message, retry_count
        """
        pending_queue = PendingQueue(state_dir=str(tmp_path))

        msg = PendingMessage(
            message_id=456,
            chat_id=123,
            update_id=789,
            message={"id": 456, "text": "test message", "sender_id": 100},
            retry_count=2,
            last_attempt="2024-01-15T10:00:00Z",
        )
        pending_queue.append(msg)

        # Read file directly
        queue_file = tmp_path / "bot_pending.jsonl"
        assert queue_file.exists()

        with open(queue_file, 'r') as f:
            line = f.readline().strip()
            data = json.loads(line)

        assert "message_id" in data
        assert data["message_id"] == 456
        assert "chat_id" in data
        assert data["chat_id"] == 123
        assert "update_id" in data
        assert data["update_id"] == 789
        assert "message" in data
        assert isinstance(data["message"], dict)
        assert "retry_count" in data
        assert data["retry_count"] == 2
        assert "last_attempt" in data

    def test_dead_letter_file_format(self, tmp_path):
        """
        Given: Message exceeds max retries
        When: Message is moved to dead-letter
        Then: File is JSON Lines
        And: Each entry contains: message_id, chat_id, message, exec_cmd, failed_at, retry_count, error
        """
        dead_letter_path = str(tmp_path / "bot_dead.jsonl")
        dead_queue = DeadLetterQueue(dead_letter_path)

        dl = DeadLetter(
            message_id=456,
            chat_id=123,
            message={"id": 456, "text": "failed message"},
            exec_cmd="my-processor --arg value",
            failed_at="2024-01-15T10:00:00Z",
            retry_count=3,
            error="Processor timeout after 30 minutes",
        )
        dead_queue.append(dl)

        # Read file directly
        assert os.path.exists(dead_letter_path)

        with open(dead_letter_path, 'r') as f:
            line = f.readline().strip()
            data = json.loads(line)

        assert data["message_id"] == 456
        assert data["chat_id"] == 123
        assert "message" in data
        assert data["exec_cmd"] == "my-processor --arg value"
        assert "failed_at" in data
        assert data["retry_count"] == 3
        assert data["error"] == "Processor timeout after 30 minutes"

    def test_fatal_queue_file_format(self, tmp_path):
        """
        Given: Processor returns fatal status
        When: Message is moved to fatal queue
        Then: File is JSON Lines
        And: Each entry contains: message_id, chat_id, message, exec_cmd, failed_at, reason
        """
        fatal_path = str(tmp_path / "bot_fatal.jsonl")
        fatal_queue = FatalQueue(fatal_path)

        fe = FatalError(
            message_id=456,
            chat_id=123,
            message={"id": 456, "text": "fatal message"},
            exec_cmd="my-processor",
            failed_at="2024-01-15T10:00:00Z",
            reason="Video not found: 404",
        )
        fatal_queue.append(fe)

        # Read file directly
        assert os.path.exists(fatal_path)

        with open(fatal_path, 'r') as f:
            line = f.readline().strip()
            data = json.loads(line)

        assert data["message_id"] == 456
        assert data["chat_id"] == 123
        assert "message" in data
        assert data["exec_cmd"] == "my-processor"
        assert "failed_at" in data
        assert data["reason"] == "Video not found: 404"

    def test_backward_compatibility_old_state_readable(self, tmp_path):
        """
        Given: State file in "old format" exists
        When: New code reads the file
        Then: File is parsed successfully
        And: No error is raised
        And: Default values are used for missing fields
        """
        # Create old format bot state file
        old_state_file = tmp_path / "bot.json"
        with open(old_state_file, 'w') as f:
            json.dump({"last_update_id": 100}, f)  # Missing last_processed_at

        state_mgr = BotStateManager(str(tmp_path))
        state = state_mgr.load()

        # Should load successfully with default for missing field
        assert state["last_update_id"] == 100
        # last_processed_at should be None or have a default
        assert state["last_processed_at"] is None or isinstance(state["last_processed_at"], str)

    def test_pending_queue_multiple_entries(self, tmp_path):
        """
        Given: Multiple messages in pending queue
        When: File is read
        Then: All entries are read in order
        And: Each entry is valid JSON
        """
        pending_queue = PendingQueue(state_dir=str(tmp_path))

        # Add multiple messages
        for i in range(5):
            msg = PendingMessage(
                message_id=i,
                chat_id=123,
                update_id=i * 100,
                message={"id": i, "text": f"message {i}"},
                retry_count=0,
            )
            pending_queue.append(msg)

        # Read all
        messages = pending_queue.read_all()

        assert len(messages) == 5
        for i, msg in enumerate(messages):
            assert msg.message_id == i
            assert msg.message["text"] == f"message {i}"

    def test_pending_queue_remove_preserves_others(self, tmp_path):
        """
        Given: Multiple messages in pending queue
        When: Some messages are removed
        Then: Remaining messages are preserved
        And: File format is still valid
        """
        pending_queue = PendingQueue(state_dir=str(tmp_path))

        # Add messages
        for i in range(5):
            msg = PendingMessage(
                message_id=i,
                chat_id=123,
                update_id=i * 100,
                message={"id": i},
                retry_count=0,
            )
            pending_queue.append(msg)

        # Remove some
        pending_queue.remove([1, 3])

        # Verify remaining
        messages = pending_queue.read_all()
        assert len(messages) == 3
        message_ids = [m.message_id for m in messages]
        assert 0 in message_ids
        assert 1 not in message_ids
        assert 2 in message_ids
        assert 3 not in message_ids
        assert 4 in message_ids

    def test_app_mode_state_file_format(self, tmp_path):
        """
        Given: App mode saves state
        When: State file is written
        Then: File is valid JSON
        And: Contains last_message_id and last_processed_at
        """
        state_mgr = StateManager(str(tmp_path))

        state = state_mgr.update(chat_id=123, last_message_id=456)

        # Read file directly
        state_file = tmp_path / "123.json"
        assert state_file.exists()

        with open(state_file, 'r') as f:
            data = json.load(f)

        assert data["last_message_id"] == 456
        assert "last_processed_at" in data
        assert "chat_id" in data

    def test_empty_queue_returns_empty_list(self, tmp_path):
        """
        Given: Queue file does not exist
        When: read_all is called
        Then: Empty list is returned
        And: No error is raised
        """
        pending_queue = PendingQueue(state_dir=str(tmp_path))
        messages = pending_queue.read_all()

        assert messages == []

        dead_queue = DeadLetterQueue(str(tmp_path / "nonexistent.jsonl"))
        entries = dead_queue.read_all()

        assert entries == []

    def test_corrupted_line_skipped(self, tmp_path):
        """
        Given: Queue file has corrupted line
        When: read_all is called
        Then: Valid lines are read
        And: Corrupted lines are skipped
        And: No error is raised
        """
        # Write file with one corrupted line
        queue_file = tmp_path / "bot_pending.jsonl"
        with open(queue_file, 'w') as f:
            f.write('{"message_id": 1, "chat_id": 123, "update_id": 100, "message": {}, "retry_count": 0}\n')
            f.write('this is not valid json\n')
            f.write('{"message_id": 2, "chat_id": 123, "update_id": 200, "message": {}, "retry_count": 0}\n')

        pending_queue = PendingQueue(state_dir=str(tmp_path))
        messages = pending_queue.read_all()

        # Should read valid entries and skip corrupted one
        assert len(messages) == 2
        assert messages[0].message_id == 1
        assert messages[1].message_id == 2

    def test_state_file_atomic_write(self, tmp_path):
        """
        Given: State file is being updated
        When: Write operation completes
        Then: File contains valid JSON
        And: No partial/corrupted data
        """
        state_mgr = BotStateManager(str(tmp_path))

        # Write multiple times
        for i in range(10):
            state_mgr.save(chat_id=123, update_id=i * 10)

        # Final read should be valid
        state = state_mgr.load(123)
        assert state["last_update_id"] == 90

    def test_chat_state_dataclass_format(self, tmp_path):
        """
        Given: ChatState is saved
        When: File is written
        Then: All fields are serialized correctly
        """
        state_mgr = StateManager(str(tmp_path))

        state = ChatState(
            last_message_id=456,
            last_processed_at="2024-01-15T10:00:00Z",
            chat_id=123,
        )
        state_mgr.save(123, state)

        # Read and verify
        loaded = state_mgr.load(123)
        assert loaded.last_message_id == 456
        assert loaded.last_processed_at == "2024-01-15T10:00:00Z"
        assert loaded.chat_id == 123