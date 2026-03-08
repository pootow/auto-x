"""Integration tests for tele CLI."""

import json
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest


class MockMessage:
    """Mock Telethon message."""

    def __init__(self, id, text="test", sender_id=123, chat_id=456):
        self.id = id
        self.text = text
        self.sender_id = sender_id
        self.date = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        self.chat_id = chat_id
        self.forward = None
        self.media = None
        self.reactions = None


class TestCLIIntegration:
    """Integration tests for CLI."""

    def test_cli_help(self):
        """Test CLI --help works."""
        result = subprocess.run(
            ["uv", "run", "tele", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Telegram message processing" in result.stdout

    def test_cli_missing_chat(self):
        """Test CLI errors without chat."""
        result = subprocess.run(
            ["uv", "run", "tele"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_cli_invalid_filter_syntax(self):
        """Test CLI handles filter syntax errors."""
        # This would need real Telegram to test fully
        # For now, just verify the filter parser handles errors
        from tele.filter import create_filter
        with pytest.raises(SyntaxError):
            create_filter('contains("unclosed')


class TestFilterPipeline:
    """Test filter pipeline without Telegram."""

    def test_filter_e2e(self):
        """End-to-end filter test with mock messages."""
        from tele.filter import create_filter

        filt = create_filter('contains("urgent") && sender_id == 123')

        msg1 = MockMessage(id=1, text="urgent meeting", sender_id=123)
        msg2 = MockMessage(id=2, text="urgent meeting", sender_id=456)
        msg3 = MockMessage(id=3, text="normal message", sender_id=123)

        assert filt.matches(msg1) is True
        assert filt.matches(msg2) is False
        assert filt.matches(msg3) is False

    def test_output_format_e2e(self):
        """End-to-end output format test."""
        from tele.output import format_message

        msg = MockMessage(id=1, text="test message", sender_id=123, chat_id=456)
        output = format_message(msg)
        data = json.loads(output)

        assert data["id"] == 1
        assert data["text"] == "test message"
        assert data["sender_id"] == 123
        assert data["chat_id"] == 456


class TestStatePipeline:
    """Test state management pipeline."""

    def test_state_incremental_logic(self, tmp_path):
        """Test incremental processing logic."""
        from tele.state import StateManager

        manager = StateManager(str(tmp_path))

        # First run - no state
        state = manager.load(123456)
        assert state.last_message_id == 0

        # After processing message 100
        manager.update(123456, 100)
        state = manager.load(123456)
        assert state.last_message_id == 100

        # After processing more messages
        manager.update(123456, 250)
        state = manager.load(123456)
        assert state.last_message_id == 250


class TestConfigPipeline:
    """Test configuration pipeline."""

    def test_config_env_override(self, monkeypatch):
        """Test environment variable override."""
        monkeypatch.setenv("TELEGRAM_API_ID", "99999")
        monkeypatch.setenv("TELEGRAM_API_HASH", "test_hash")

        from tele.config import load_config
        config = load_config()

        assert config.telegram.api_id == 99999
        assert config.telegram.api_hash == "test_hash"


class TestMarkMode:
    """Test mark mode pipeline."""

    def test_parse_mark_input(self):
        """Test parsing mark mode input."""
        from tele.output import parse_message_id

        line = '{"id": 123, "chat_id": 456}'
        msg_id, chat_id = parse_message_id(line)

        assert msg_id == 123
        assert chat_id == 456

    def test_mark_mode_simulation(self, tmp_path):
        """Simulate mark mode flow without Telegram."""
        from tele.state import StateManager
        from tele.output import format_message, parse_message_id

        # Simulate: get messages -> output -> parse -> mark
        msg = MockMessage(id=100, chat_id=123456)

        # Output
        output = format_message(msg)

        # Parse (simulating stdin read)
        msg_id, chat_id = parse_message_id(output)

        assert msg_id == 100
        assert chat_id == 123456