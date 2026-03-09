"""Tests for bot state management."""

import os
import tempfile

import pytest

from tele.state import BotStateManager


class TestBotStateManager:
    """Test cases for BotStateManager."""

    def test_load_empty_state(self):
        """BotStateManager should return default state when no state file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BotStateManager(tmpdir)
            state = manager.load(123)

            assert state["last_update_id"] == 0
            assert state["last_processed_at"] is None

    def test_save_and_load_state(self):
        """BotStateManager should save and load state correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BotStateManager(tmpdir)
            manager.save(123, 456)

            state = manager.load(123)
            assert state["last_update_id"] == 456
            assert state["last_processed_at"] is not None

    def test_load_existing_state(self):
        """BotStateManager should load existing state from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "bot_123.json")
            with open(state_file, "w") as f:
                f.write('{"last_update_id": 789, "last_processed_at": "2024-01-15T10:00:00Z"}')

            manager = BotStateManager(tmpdir)
            state = manager.load(123)

            assert state["last_update_id"] == 789
            assert state["last_processed_at"] == "2024-01-15T10:00:00Z"

    def test_different_chats_have_separate_state(self):
        """Different chats should have separate state files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BotStateManager(tmpdir)
            manager.save(123, 100)
            manager.save(456, 200)

            state_123 = manager.load(123)
            state_456 = manager.load(456)

            assert state_123["last_update_id"] == 100
            assert state_456["last_update_id"] == 200