"""Tests for bot state management."""

import os
import tempfile

import pytest

from tele.state import BotStateManager


class TestBotStateManager:
    """Test cases for BotStateManager.

    Bot state is global (not per-chat) because Telegram's getUpdates offset
    is global. All tests reflect this single-file design.
    """

    def test_load_empty_state(self):
        """BotStateManager should return default state when no state file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BotStateManager(tmpdir)
            state = manager.load()

            assert state["last_update_id"] == 0
            assert state["last_processed_at"] is None

    def test_save_and_load_state(self):
        """BotStateManager should save and load state correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BotStateManager(tmpdir)
            manager.save(456)

            state = manager.load()
            assert state["last_update_id"] == 456
            assert state["last_processed_at"] is not None

    def test_load_existing_state(self):
        """BotStateManager should load existing state from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "bot.json")
            with open(state_file, "w") as f:
                f.write('{"last_update_id": 789, "last_processed_at": "2024-01-15T10:00:00Z"}')

            manager = BotStateManager(tmpdir)
            state = manager.load()

            assert state["last_update_id"] == 789
            assert state["last_processed_at"] == "2024-01-15T10:00:00Z"

    def test_state_file_path(self):
        """State file should be at fixed path (bot.json)."""
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BotStateManager(tmpdir)
            assert manager._state_path() == Path(tmpdir) / "bot.json"

    def test_save_overwrites_existing_state(self):
        """Save should overwrite existing state (global state is singleton)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = BotStateManager(tmpdir)
            manager.save(100)

            state = manager.load()
            assert state["last_update_id"] == 100

            # Save again with different value
            manager.save(200)

            state = manager.load()
            assert state["last_update_id"] == 200
            # Only one state file exists
            assert len([f for f in os.listdir(tmpdir) if f.endswith('.json')]) == 1