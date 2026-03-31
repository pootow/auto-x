"""Integration tests for source ingest flow.

Tests the interaction between:
- SourceStateManager - state persistence
- SourceConsumer - message consumption
- SourceWatcher - file change detection
"""

import pytest
import asyncio
import json
from pathlib import Path

from tele.source_state import SourceStateManager, SourceState
from tele.source_consumer import SourceConsumer, consume_from_offset
from tele.source_watcher import SourceWatcher


class TestIngestIntegration:
    """Integration tests for source ingest flow."""

    @pytest.mark.asyncio
    async def test_full_consume_flow(self, tmp_path):
        """Test complete flow: write -> consume -> process."""
        state_dir = tmp_path / "state"
        state_mgr = SourceStateManager(state_dir=state_dir)

        source_dir = state_mgr.get_source_dir("test_source")
        source_dir.mkdir(parents=True)

        incoming = source_dir / "incoming.2026-03-31.jsonl"
        messages = [
            {"id": "msg1", "text": "first message", "date": "2026-03-31T10:00:00Z"},
            {"id": "msg2", "text": "second message", "date": "2026-03-31T11:00:00Z"},
        ]
        # Use binary mode for consistent LF line endings across platforms
        with open(incoming, 'wb') as f:
            for msg in messages:
                f.write((json.dumps(msg) + '\n').encode('utf-8'))

        consumer = SourceConsumer("test_source", state_mgr)
        consumed = consumer.consume_available()

        assert len(consumed) == 2
        assert consumed[0]["id"] == "msg1"
        assert consumed[1]["id"] == "msg2"

        state = state_mgr.load("test_source")
        assert state.current_file == "incoming.2026-03-31.jsonl"
        assert state.byte_offset == incoming.stat().st_size

        # Append more messages
        with open(incoming, 'ab') as f:
            f.write((json.dumps({"id": "msg3", "text": "third"}) + '\n').encode('utf-8'))

        consumed2 = consumer.consume_available()
        assert len(consumed2) == 1
        assert consumed2[0]["id"] == "msg3"

    @pytest.mark.asyncio
    async def test_multi_date_file_switching(self, tmp_path):
        """Test switching between files with different dates."""
        state_dir = tmp_path / "state"
        state_mgr = SourceStateManager(state_dir=state_dir)

        source_dir = state_mgr.get_source_dir("test_source")
        source_dir.mkdir(parents=True)

        day1 = source_dir / "incoming.2026-03-30.jsonl"
        day2 = source_dir / "incoming.2026-03-31.jsonl"

        # Use binary mode for consistent LF line endings across platforms
        with open(day1, 'wb') as f:
            f.write((json.dumps({"id": "d1-1", "text": "day1 msg1"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": "d1-2", "text": "day1 msg2"}) + '\n').encode('utf-8'))

        with open(day2, 'wb') as f:
            f.write((json.dumps({"id": "d2-1", "text": "day2 msg1"}) + '\n').encode('utf-8'))

        consumer = SourceConsumer("test_source", state_mgr)
        all_consumed = consumer.consume_available()

        assert len(all_consumed) == 3
        assert all_consumed[0]["id"] == "d1-1"
        assert all_consumed[2]["id"] == "d2-1"

        state = state_mgr.load("test_source")
        assert state.current_file == "incoming.2026-03-31.jsonl"

    @pytest.mark.asyncio
    async def test_watcher_detects_append(self, tmp_path):
        """Watcher should detect appended content."""
        state_dir = tmp_path / "state"
        watcher = SourceWatcher(state_dir=state_dir, poll_interval=0.1)

        source_dir = state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)

        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Initialize state for this source
        watcher.state_manager.save("test_source", SourceState.new())

        # Write initial content
        with open(incoming, 'wb') as f:
            f.write((json.dumps({"id": 1}) + '\n').encode('utf-8'))

        # Wait a moment for file system
        await asyncio.sleep(0.1)

        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources

        # Consume to update state
        consumer = SourceConsumer("test_source", watcher.state_manager)
        consumer.consume_available()

        # Should no longer have changes
        sources = watcher.get_sources_with_changes()
        assert "test_source" not in sources

        # Append more content
        with open(incoming, 'ab') as f:
            f.write((json.dumps({"id": 2}) + '\n').encode('utf-8'))

        await asyncio.sleep(0.1)

        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources


class TestWatcherConsumerIntegration:
    """Integration tests for watcher and consumer interaction."""

    @pytest.fixture
    def temp_state_dir(self, tmp_path):
        """Create a temporary directory for state files."""
        return tmp_path / "state"

    @pytest.mark.asyncio
    async def test_watcher_then_consume_cycle(self, temp_state_dir):
        """Test the watch -> consume -> watch cycle."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=0.1)

        source_dir = temp_state_dir / "sources" / "my_source"
        source_dir.mkdir(parents=True)

        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Initialize state
        watcher.state_manager.save("my_source", SourceState.new())

        # No content yet, no changes detected
        sources = watcher.get_sources_with_changes()
        assert "my_source" not in sources

        # Add content
        with open(incoming, 'wb') as f:
            f.write((json.dumps({"id": "msg1", "text": "hello"}) + '\n').encode('utf-8'))

        await asyncio.sleep(0.05)

        # Now should detect changes
        sources = watcher.get_sources_with_changes()
        assert "my_source" in sources

        # Consume messages
        consumer = SourceConsumer("my_source", watcher.state_manager)
        messages = consumer.consume_available()
        assert len(messages) == 1
        assert messages[0]["id"] == "msg1"

        # No more changes
        sources = watcher.get_sources_with_changes()
        assert "my_source" not in sources

    @pytest.mark.asyncio
    async def test_multiple_sources_independent_tracking(self, temp_state_dir):
        """Test that multiple sources are tracked independently."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=0.1)

        # Create two sources
        source1_dir = temp_state_dir / "sources" / "source_one"
        source1_dir.mkdir(parents=True)
        source2_dir = temp_state_dir / "sources" / "source_two"
        source2_dir.mkdir(parents=True)

        # Initialize states
        watcher.state_manager.save("source_one", SourceState.new())
        watcher.state_manager.save("source_two", SourceState.new())

        # Add content to source_one
        incoming1 = source1_dir / "incoming.2026-03-31.jsonl"
        with open(incoming1, 'wb') as f:
            f.write((json.dumps({"id": 1}) + '\n').encode('utf-8'))

        await asyncio.sleep(0.05)

        # Only source_one should have changes
        sources = watcher.get_sources_with_changes()
        assert "source_one" in sources
        assert "source_two" not in sources

        # Add content to source_two
        incoming2 = source2_dir / "incoming.2026-03-31.jsonl"
        with open(incoming2, 'wb') as f:
            f.write((json.dumps({"id": 2}) + '\n').encode('utf-8'))

        await asyncio.sleep(0.05)

        # Both should have changes
        sources = watcher.get_sources_with_changes()
        assert "source_one" in sources
        assert "source_two" in sources

        # Consume from source_one only
        consumer1 = SourceConsumer("source_one", watcher.state_manager)
        consumer1.consume_available()

        # Now only source_two has changes
        sources = watcher.get_sources_with_changes()
        assert "source_one" not in sources
        assert "source_two" in sources

    @pytest.mark.asyncio
    async def test_state_persistence_across_consumer_instances(self, temp_state_dir):
        """Test that state persists across different consumer instances."""
        state_mgr = SourceStateManager(state_dir=temp_state_dir)

        source_dir = state_mgr.get_source_dir("persistent_source")
        source_dir.mkdir(parents=True)

        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Write three messages
        with open(incoming, 'wb') as f:
            f.write((json.dumps({"id": "a"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": "b"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": "c"}) + '\n').encode('utf-8'))

        # First consumer reads all
        consumer1 = SourceConsumer("persistent_source", state_mgr)
        messages1 = consumer1.consume_available()
        assert len(messages1) == 3

        # Add more messages
        with open(incoming, 'ab') as f:
            f.write((json.dumps({"id": "d"}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": "e"}) + '\n').encode('utf-8'))

        # Second consumer (new instance) should only see new messages
        consumer2 = SourceConsumer("persistent_source", state_mgr)
        messages2 = consumer2.consume_available()
        assert len(messages2) == 2
        assert messages2[0]["id"] == "d"
        assert messages2[1]["id"] == "e"


class TestConsumeFromOffsetEdgeCases:
    """Edge case tests for consume_from_offset function."""

    def test_empty_lines_skipped(self, tmp_path):
        """Empty lines should be skipped."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        with open(file_path, 'wb') as f:
            f.write(b'\n')  # Empty line
            f.write((json.dumps({"id": 1}) + '\n').encode('utf-8'))
            f.write(b'\n')  # Empty line
            f.write((json.dumps({"id": 2}) + '\n').encode('utf-8'))

        messages, offset = consume_from_offset(file_path, 0)
        assert len(messages) == 2
        assert messages[0]["id"] == 1
        assert messages[1]["id"] == 2

    def test_large_file_offset_handling(self, tmp_path):
        """Test that offset works correctly for larger files."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"

        # Write many messages
        expected_count = 100
        with open(file_path, 'wb') as f:
            for i in range(expected_count):
                msg = {"id": i, "text": f"message {i}" + "x" * 100}
                f.write((json.dumps(msg) + '\n').encode('utf-8'))

        # Read all
        messages, offset = consume_from_offset(file_path, 0)
        assert len(messages) == expected_count
        assert offset == file_path.stat().st_size

        # Read from middle
        half_offset = offset // 2
        messages2, offset2 = consume_from_offset(file_path, half_offset)
        # Should have read some messages
        assert len(messages2) > 0
        assert offset2 > half_offset

    def test_unicode_content_preserved(self, tmp_path):
        """Unicode content should be preserved correctly."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        test_messages = [
            {"id": 1, "text": "Hello World"},
            {"id": 2, "text": "Chinese: 你好世界"},
            {"id": 3, "text": "Emoji: \U0001F600"},
            {"id": 4, "text": "Mixed: Hello \u4e16\u754c \U0001F310"},
        ]

        with open(file_path, 'wb') as f:
            for msg in test_messages:
                f.write((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))

        messages, _ = consume_from_offset(file_path, 0)
        assert len(messages) == 4
        assert messages[0]["text"] == "Hello World"
        assert messages[1]["text"] == "Chinese: \u4f60\u597d\u4e16\u754c"
        assert messages[2]["text"] == "Emoji: \U0001F600"
        assert messages[3]["text"] == "Mixed: Hello \u4e16\u754c \U0001F310"


class TestFileRotation:
    """Tests for file rotation and date-based switching."""

    def test_consume_from_older_to_newer_file(self, tmp_path):
        """Consumer should automatically switch from older to newer files."""
        state_mgr = SourceStateManager(state_dir=tmp_path)

        source_dir = state_mgr.get_source_dir("rotating_source")
        source_dir.mkdir(parents=True)

        # Create files for three days
        day1 = source_dir / "incoming.2026-03-28.jsonl"
        day2 = source_dir / "incoming.2026-03-29.jsonl"
        day3 = source_dir / "incoming.2026-03-30.jsonl"

        with open(day1, 'wb') as f:
            f.write((json.dumps({"day": 1, "msg": 1}) + '\n').encode('utf-8'))
            f.write((json.dumps({"day": 1, "msg": 2}) + '\n').encode('utf-8'))

        with open(day2, 'wb') as f:
            f.write((json.dumps({"day": 2, "msg": 1}) + '\n').encode('utf-8'))

        with open(day3, 'wb') as f:
            f.write((json.dumps({"day": 3, "msg": 1}) + '\n').encode('utf-8'))
            f.write((json.dumps({"day": 3, "msg": 2}) + '\n').encode('utf-8'))
            f.write((json.dumps({"day": 3, "msg": 3}) + '\n').encode('utf-8'))

        consumer = SourceConsumer("rotating_source", state_mgr)
        messages = consumer.consume_available()

        # Should have consumed all messages in order
        assert len(messages) == 6
        assert messages[0]["day"] == 1
        assert messages[2]["day"] == 2
        assert messages[3]["day"] == 3

        # State should be on last file
        state = state_mgr.load("rotating_source")
        assert state.current_file == "incoming.2026-03-30.jsonl"
        assert state.byte_offset == day3.stat().st_size

    def test_consume_resumes_mid_file(self, tmp_path):
        """Consumer should resume from offset in middle of file."""
        state_mgr = SourceStateManager(state_dir=tmp_path)

        source_dir = state_mgr.get_source_dir("mid_source")
        source_dir.mkdir(parents=True)

        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Write initial messages
        with open(incoming, 'wb') as f:
            f.write((json.dumps({"id": 1}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 2}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 3}) + '\n').encode('utf-8'))

        # Consume first batch
        consumer = SourceConsumer("mid_source", state_mgr)
        first_batch = consumer.consume_available()
        assert len(first_batch) == 3

        # Add more to same file
        with open(incoming, 'ab') as f:
            f.write((json.dumps({"id": 4}) + '\n').encode('utf-8'))
            f.write((json.dumps({"id": 5}) + '\n').encode('utf-8'))

        # Add a new day's file
        next_day = source_dir / "incoming.2026-04-01.jsonl"
        with open(next_day, 'wb') as f:
            f.write((json.dumps({"id": 6}) + '\n').encode('utf-8'))

        # Consume again
        second_batch = consumer.consume_available()
        assert len(second_batch) == 3
        assert second_batch[0]["id"] == 4
        assert second_batch[1]["id"] == 5
        assert second_batch[2]["id"] == 6

        # State should be on newest file
        state = state_mgr.load("mid_source")
        assert state.current_file == "incoming.2026-04-01.jsonl"