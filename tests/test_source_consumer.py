"""Tests for source file consumer."""

import pytest
import json
from pathlib import Path
from tele.source_consumer import SourceConsumer, consume_from_offset


class TestConsumeFromOffset:
    """Tests for consume_from_offset function."""

    def test_consume_from_empty_file(self, tmp_path):
        """consume_from_offset returns empty list for empty file."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        file_path.touch()

        messages, new_offset = consume_from_offset(file_path, 0)
        assert messages == []
        assert new_offset == 0

    def test_consume_from_offset_zero(self, tmp_path):
        """consume_from_offset reads all messages from beginning."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(file_path, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "msg1"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 2, "text": "msg2"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 3, "text": "msg3"}) + '\n').encode('utf-8'))

        messages, new_offset = consume_from_offset(file_path, 0)
        assert len(messages) == 3
        assert messages[0]["id"] == 1
        assert messages[2]["id"] == 3
        assert new_offset == file_path.stat().st_size

    def test_consume_from_middle_offset(self, tmp_path):
        """consume_from_offset reads only messages after offset."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(file_path, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "msg1"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 2, "text": "msg2"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 3, "text": "msg3"}) + '\n').encode('utf-8'))

        first_line = json.dumps({"id": 1, "text": "msg1"}) + '\n'
        offset_after_first = len(first_line.encode('utf-8'))

        messages, new_offset = consume_from_offset(file_path, offset_after_first)
        assert len(messages) == 2
        assert messages[0]["id"] == 2
        assert messages[1]["id"] == 3

    def test_consume_handles_partial_line(self, tmp_path):
        """consume_from_offset skips incomplete lines at end."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(file_path, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "complete"}) + '\n').encode('utf-8'))
            f.write('{"id": 2, "text": "incomplete...'.encode('utf-8'))  # No newline

        messages, new_offset = consume_from_offset(file_path, 0)
        assert len(messages) == 1
        assert messages[0]["id"] == 1

    def test_consume_handles_unicode(self, tmp_path):
        """consume_from_offset handles multi-byte unicode correctly."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(file_path, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "你好世界"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 2, "text": "msg2"}) + '\n').encode('utf-8'))

        messages, new_offset = consume_from_offset(file_path, 0)
        assert len(messages) == 2

        # Verify offset works for seek
        with open(file_path, 'rb') as f:
            f.seek(new_offset)
            remaining = f.read()
        assert len(remaining) == 0

    def test_consume_nonexistent_file(self, tmp_path):
        """consume_from_offset handles missing file gracefully."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Don't create the file

        messages, new_offset = consume_from_offset(file_path, 0)
        assert messages == []
        assert new_offset == 0

    def test_consume_file_with_only_partial_line(self, tmp_path):
        """consume_from_offset handles file with only incomplete line."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent behavior
        with open(file_path, 'wb') as f:
            f.write('{"id": 1, "text": "incomplete"'.encode('utf-8'))  # No newline

        messages, new_offset = consume_from_offset(file_path, 0)
        assert messages == []
        assert new_offset == 0  # Should not advance offset for partial line

    def test_consume_multiple_partial_lines_ignored(self, tmp_path):
        """consume_from_offset ignores multiple partial lines at end."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(file_path, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "complete"}) + '\n').encode('utf-8'))
            f.write('{"id": 2, "text": "partial1"'.encode('utf-8'))  # No newline
            # Note: can't have two partial lines without newline between them
            # But we can have complete + partial

        messages, new_offset = consume_from_offset(file_path, 0)
        assert len(messages) == 1
        assert messages[0]["id"] == 1
        # Offset should point to end of last complete line (byte count, not char count)
        expected_offset = len((json.dumps({"id": 1, "text": "complete"}) + '\n').encode('utf-8'))
        assert new_offset == expected_offset


class TestSourceConsumer:
    """Tests for SourceConsumer class."""

    def test_consume_from_empty_source(self, tmp_path):
        """SourceConsumer handles source with no files."""
        from tele.source_state import SourceStateManager

        manager = SourceStateManager(state_dir=tmp_path)
        consumer = SourceConsumer("test_source", manager)

        messages = consumer.consume_available()
        assert messages == []

    def test_consume_single_file(self, tmp_path):
        """SourceConsumer consumes messages from single file."""
        from tele.source_state import SourceStateManager

        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True, exist_ok=True)

        # Create incoming file with messages
        incoming_file = source_dir / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(incoming_file, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "msg1"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 2, "text": "msg2"}) + '\n').encode('utf-8'))

        consumer = SourceConsumer("test_source", manager)
        messages = consumer.consume_available()

        assert len(messages) == 2
        assert messages[0]["id"] == 1
        assert messages[1]["id"] == 2

    def test_consume_across_multiple_files(self, tmp_path):
        """SourceConsumer switches to next file when current exhausted."""
        from tele.source_state import SourceStateManager

        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True, exist_ok=True)

        # Create multiple incoming files
        file1 = source_dir / "incoming.2026-03-30.jsonl"
        file2 = source_dir / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(file1, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "file1_msg"}) + '\n').encode('utf-8'))
        with open(file2, 'wb') as f:
            f.write((json.dumps({"id": 2, "text": "file2_msg"}) + '\n').encode('utf-8'))

        consumer = SourceConsumer("test_source", manager)
        messages = consumer.consume_available()

        assert len(messages) == 2
        assert messages[0]["id"] == 1
        assert messages[1]["id"] == 2

    def test_state_persists_across_consumes(self, tmp_path):
        """SourceConsumer updates state and resumes from offset."""
        from tele.source_state import SourceStateManager

        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True, exist_ok=True)

        incoming_file = source_dir / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(incoming_file, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "msg1"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 2, "text": "msg2"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 3, "text": "msg3"}) + '\n').encode('utf-8'))

        # First consumer reads all
        consumer1 = SourceConsumer("test_source", manager)
        messages1 = consumer1.consume_available()
        assert len(messages1) == 3

        # Add more messages (simulating partial line being completed)
        with open(incoming_file, 'ab') as f:
            f.write((json.dumps({"id": 4, "text": "msg4"}) + '\n').encode('utf-8'))

        # Second consumer should only see new messages
        consumer2 = SourceConsumer("test_source", manager)
        messages2 = consumer2.consume_available()
        assert len(messages2) == 1
        assert messages2[0]["id"] == 4

    def test_consume_handles_partial_line_at_end(self, tmp_path):
        """SourceConsumer doesn't consume partial lines (mid-write)."""
        from tele.source_state import SourceStateManager

        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True, exist_ok=True)

        incoming_file = source_dir / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(incoming_file, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "complete"}) + '\n').encode('utf-8'))
            f.write('{"id": 2, "text": "partial'.encode('utf-8'))  # No newline

        consumer = SourceConsumer("test_source", manager)
        messages = consumer.consume_available()

        assert len(messages) == 1
        assert messages[0]["id"] == 1

    def test_consume_resumes_from_existing_state(self, tmp_path):
        """SourceConsumer resumes from existing state offset."""
        from tele.source_state import SourceStateManager

        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True, exist_ok=True)

        incoming_file = source_dir / "incoming.2026-03-31.jsonl"
        # Use binary mode for consistent LF line endings across platforms
        with open(incoming_file, 'wb') as f:
            f.write((json.dumps({"id": 1, "text": "msg1"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 2, "text": "msg2"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 3, "text": "msg3"}) + '\n').encode('utf-8'))

        # Set up existing state pointing past first message
        first_line = json.dumps({"id": 1, "text": "msg1"}) + '\n'
        offset = len(first_line.encode('utf-8'))
        manager.update_offset("test_source", "incoming.2026-03-31.jsonl", offset)

        consumer = SourceConsumer("test_source", manager)
        messages = consumer.consume_available()

        assert len(messages) == 2
        assert messages[0]["id"] == 2
        assert messages[1]["id"] == 3