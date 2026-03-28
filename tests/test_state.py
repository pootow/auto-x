"""Tests for state management."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tele.state import StateManager, ChatState, PendingMessage, PendingQueue


class TestPendingMessage:
    """Test cases for PendingMessage dataclass."""

    def test_pending_message_ready_at_default(self):
        """PendingMessage should have ready_at default to None."""
        msg = PendingMessage(
            message_id=1,
            chat_id=123,
            update_id=100,
            message={"id": 1},
        )
        assert msg.ready_at is None

    def test_pending_message_ready_at_can_be_set(self):
        """PendingMessage should accept ready_at timestamp."""
        msg = PendingMessage(
            message_id=1,
            chat_id=123,
            update_id=100,
            message={"id": 1},
            ready_at="2024-01-15T10:05:00Z",
        )
        assert msg.ready_at == "2024-01-15T10:05:00Z"


class TestChatState:
    """Test cases for ChatState dataclass."""

    def test_new_state(self):
        """Test creating new state."""
        state = ChatState.new()
        assert state.last_message_id == 0
        assert state.last_processed_at is not None
        assert state.chat_id is None

    def test_new_state_with_chat_id(self):
        """Test creating new state with chat_id."""
        state = ChatState.new(chat_id=123456)
        assert state.chat_id == 123456


class TestStateManager:
    """Test cases for StateManager."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create a temporary directory for state files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init_creates_directory(self, temp_state_dir):
        """Test that StateManager creates the state directory."""
        state_dir = os.path.join(temp_state_dir, "state")
        StateManager(state_dir)
        assert os.path.exists(state_dir)

    def test_load_new_state(self, temp_state_dir):
        """Test loading state for a new chat."""
        manager = StateManager(temp_state_dir)
        state = manager.load(123456)
        assert state.last_message_id == 0
        assert state.chat_id is None

    def test_save_and_load_state(self, temp_state_dir):
        """Test saving and loading state."""
        manager = StateManager(temp_state_dir)

        # Save state
        state = ChatState(
            last_message_id=100,
            last_processed_at="2024-01-15T10:30:00Z",
            chat_id=123456,
        )
        manager.save(123456, state)

        # Load state
        loaded = manager.load(123456)
        assert loaded.last_message_id == 100
        assert loaded.last_processed_at == "2024-01-15T10:30:00Z"
        assert loaded.chat_id == 123456

    def test_update_state(self, temp_state_dir):
        """Test updating state."""
        manager = StateManager(temp_state_dir)

        # Update state
        state = manager.update(123456, 200)

        assert state.last_message_id == 200
        assert state.last_processed_at is not None

        # Verify persistence
        loaded = manager.load(123456)
        assert loaded.last_message_id == 200

    def test_clear_state(self, temp_state_dir):
        """Test clearing state."""
        manager = StateManager(temp_state_dir)

        # Create state
        manager.update(123456, 100)
        assert manager.load(123456).last_message_id == 100

        # Clear state
        manager.clear(123456)

        # Verify cleared
        loaded = manager.load(123456)
        assert loaded.last_message_id == 0

    def test_state_file_path(self, temp_state_dir):
        """Test state file path generation."""
        manager = StateManager(temp_state_dir)
        path = manager._get_state_path(123456)
        assert path.name == "123456.json"
        assert str(path).startswith(temp_state_dir)

    def test_negative_chat_id(self, temp_state_dir):
        """Test state with negative chat IDs (groups/channels)."""
        manager = StateManager(temp_state_dir)

        # Test negative ID (group chat)
        manager.update(-1001234567890, 50)
        loaded = manager.load(-1001234567890)
        assert loaded.last_message_id == 50

    def test_string_chat_id(self, temp_state_dir):
        """Test state with string chat IDs."""
        manager = StateManager(temp_state_dir)

        manager.update("123456", 75)
        loaded = manager.load("123456")
        assert loaded.last_message_id == 75


class TestPendingQueue:
    """Test cases for PendingQueue."""

    def test_read_ready_returns_messages_with_null_ready_at(self, tmp_path):
        """Messages with ready_at=None should be returned as ready."""
        queue = PendingQueue(state_dir=str(tmp_path))

        # Add ready message
        queue.append(PendingMessage(
            message_id=1, chat_id=123, update_id=100,
            message={"id": 1}, ready_at=None
        ))
        # Add future message
        queue.append(PendingMessage(
            message_id=2, chat_id=123, update_id=101,
            message={"id": 2}, ready_at="2099-01-01T00:00:00Z"
        ))

        ready = queue.read_ready()
        assert len(ready) == 1
        assert ready[0].message_id == 1

    def test_read_ready_returns_messages_past_ready_time(self, tmp_path):
        """Messages with ready_at in the past should be returned."""
        queue = PendingQueue(state_dir=str(tmp_path))

        queue.append(PendingMessage(
            message_id=1, chat_id=123, update_id=100,
            message={"id": 1}, ready_at="2020-01-01T00:00:00Z"  # Past
        ))

        ready = queue.read_ready()
        assert len(ready) == 1
        assert ready[0].message_id == 1

    def test_read_ready_excludes_future_messages(self, tmp_path):
        """Messages with ready_at in the future should not be returned."""
        queue = PendingQueue(state_dir=str(tmp_path))

        queue.append(PendingMessage(
            message_id=1, chat_id=123, update_id=100,
            message={"id": 1}, ready_at="2099-01-01T00:00:00Z"
        ))

        ready = queue.read_ready()
        assert len(ready) == 0

    def test_append_auto_populates_created_at(self, tmp_path):
        """Appending a message should auto-populate created_at if not set."""
        queue = PendingQueue(state_dir=str(tmp_path))

        msg = PendingMessage(
            message_id=1, chat_id=123, update_id=100,
            message={"id": 1}
        )
        queue.append(msg)

        messages = queue.read_all()
        assert messages[0].created_at is not None
        # Should be recent (within last second)
        from datetime import datetime, timezone
        created = datetime.fromisoformat(messages[0].created_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = (now - created).total_seconds()
        assert 0 <= diff < 1

    def test_schedule_retry_updates_ready_at(self, tmp_path):
        """schedule_retry should update ready_at with backoff."""
        queue = PendingQueue(state_dir=str(tmp_path))

        msg = PendingMessage(
            message_id=1, chat_id=123, update_id=100,
            message={"id": 1}, retry_count=0
        )
        queue.append(msg)

        # Schedule retry with 5 second backoff
        queue.schedule_retry(1, 123, backoff_seconds=5.0)

        messages = queue.read_all()
        assert messages[0].retry_count == 1
        assert messages[0].ready_at is not None

        # ready_at should be approximately 5 seconds in the future
        from datetime import datetime, timezone
        ready = datetime.fromisoformat(messages[0].ready_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = (ready - now).total_seconds()
        assert 4.5 < diff < 5.5

    def test_schedule_retry_message_not_found(self, tmp_path):
        """schedule_retry should return False if message not found."""
        queue = PendingQueue(state_dir=str(tmp_path))

        result = queue.schedule_retry(999, 999, backoff_seconds=5.0)
        assert result is False