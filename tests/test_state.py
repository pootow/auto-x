"""Tests for state management."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from tele.state import StateManager, ChatState, PendingMessage


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