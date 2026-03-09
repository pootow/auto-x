"""Tests for output formatting."""

import json
from datetime import datetime

import pytest

from tele.output import format_message, format_messages, parse_message_id


class MockMessage:
    """Mock message for testing."""

    def __init__(
        self,
        id: int = 1,
        text: str = "Test message",
        sender_id: int = 123,
        date: datetime = None,
        chat_id: int = 789,
        forward=None,
        media=None,
        reactions=None,
    ):
        self.id = id
        self.text = text
        self.sender_id = sender_id
        self.date = date or datetime(2024, 1, 15, 10, 0, 0)
        self.chat_id = chat_id
        self.forward = forward
        self.media = media
        self.reactions = reactions


class TestFormatMessage:
    """Test cases for format_message."""

    def test_basic_message(self):
        """Test formatting a basic message."""
        msg = MockMessage()
        output = format_message(msg)
        data = json.loads(output)

        assert data["id"] == 1
        assert data["text"] == "Test message"
        assert data["sender_id"] == 123
        assert data["chat_id"] == 789

    def test_message_with_chat_id_override(self):
        """Test formatting with explicit chat_id."""
        msg = MockMessage()
        output = format_message(msg, chat_id=999)
        data = json.loads(output)

        assert data["chat_id"] == 999

    def test_message_with_forward(self):
        """Test formatting a forwarded message."""
        # Create a proper mock forward object
        class MockForward:
            def __init__(self, from_id):
                self.from_id = from_id

        msg = MockMessage(forward=MockForward(456))
        output = format_message(msg)
        data = json.loads(output)

        assert data["is_forwarded"] is True
        assert data["forward_from_id"] == 456

    def test_message_with_media(self):
        """Test formatting a message with media."""
        msg = MockMessage(media={"type": "photo"})
        output = format_message(msg)
        data = json.loads(output)

        assert data["has_media"] is True
        assert data["media_type"] == "dict"

    def test_message_with_reactions(self):
        """Test formatting a message with reactions."""
        class MockReaction:
            def __init__(self, emoji, count):
                self.reaction = type('obj', (object,), {'emoticon': emoji})()
                self.count = count

        class MockReactions:
            def __init__(self):
                self.results = [MockReaction("✅", 3), MockReaction("👍", 2)]

        msg = MockMessage(reactions=MockReactions())
        output = format_message(msg)
        data = json.loads(output)

        assert "reactions" in data
        assert len(data["reactions"]) == 2
        assert data["reactions"][0]["emoji"] == "✅"

    def test_empty_text(self):
        """Test formatting message with empty text."""
        msg = MockMessage(text="")
        output = format_message(msg)
        data = json.loads(output)

        assert data["text"] == ""

    def test_none_text(self):
        """Test formatting message with None text."""
        msg = MockMessage(text=None)
        output = format_message(msg)
        data = json.loads(output)

        assert data["text"] == ""

    def test_unicode_text(self):
        """Test formatting message with unicode text."""
        msg = MockMessage(text="你好世界 🌍")
        output = format_message(msg)
        data = json.loads(output)

        assert data["text"] == "你好世界 🌍"


class TestFormatMessages:
    """Test cases for format_messages."""

    def test_multiple_messages(self):
        """Test formatting multiple messages."""
        msgs = [MockMessage(id=1), MockMessage(id=2), MockMessage(id=3)]
        output = format_messages(msgs)
        lines = output.strip().split("\n")

        assert len(lines) == 3
        for i, line in enumerate(lines, 1):
            data = json.loads(line)
            assert data["id"] == i

    def test_empty_list(self):
        """Test formatting empty message list."""
        output = format_messages([])
        assert output == ""


class TestParseMessageId:
    """Test cases for parse_message_id."""

    def test_parse_basic(self):
        """Test parsing basic message ID."""
        line = '{"id": 123, "chat_id": 456}'
        msg_id, chat_id = parse_message_id(line)

        assert msg_id == 123
        assert chat_id == 456

    def test_parse_with_extra_fields(self):
        """Test parsing with extra fields."""
        line = '{"id": 789, "chat_id": 123, "text": "test", "sender_id": 456}'
        msg_id, chat_id = parse_message_id(line)

        assert msg_id == 789
        assert chat_id == 123


class TestStatusField:
    """Test cases for status field in output."""

    def test_format_message_no_status_by_default(self):
        """Input format should NOT include status field by default."""
        msg = MockMessage()
        output = format_message(msg)
        data = json.loads(output)

        assert "status" not in data

    def test_format_message_with_include_status(self):
        """Output format should include status when include_status=True."""
        msg = MockMessage()
        output = format_message(msg, include_status=True)
        data = json.loads(output)

        assert data["status"] == "pending"


class TestBotApiFormat:
    """Test cases for Bot API message format support."""

    def test_format_message_from_bot_api(self):
        """format_message should handle Bot API message dict."""
        bot_message = {
            "message_id": 123,
            "text": "hello from bot",
            "from": {"id": 456},
            "date": 1705312800,  # Unix timestamp
            "chat": {"id": 789}
        }

        output = format_message(bot_message)
        data = json.loads(output)

        assert data["id"] == 123
        assert data["text"] == "hello from bot"
        assert data["sender_id"] == 456
        assert data["chat_id"] == 789
        assert "status" not in data  # No status in input format

    def test_format_message_bot_api_with_include_status(self):
        """format_message should support include_status for Bot API messages."""
        bot_message = {
            "message_id": 456,
            "text": "test",
            "from": {"id": 123},
            "date": 1705312800,
            "chat": {"id": 789}
        }

        output = format_message(bot_message, include_status=True)
        data = json.loads(output)

        assert data["status"] == "pending"