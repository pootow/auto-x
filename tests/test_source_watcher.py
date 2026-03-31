"""Tests for source file watcher."""

import pytest
import asyncio
import json
from pathlib import Path
from tele.source_watcher import SourceWatcher, WatcherEvent


class TestWatcherEvent:
    """Tests for WatcherEvent dataclass."""

    def test_watcher_event_creation(self):
        """WatcherEvent should be created with required fields."""
        event = WatcherEvent(source_name="web_monitor", file_path="/path/to/file.jsonl")
        assert event.source_name == "web_monitor"
        assert event.file_path == "/path/to/file.jsonl"

    def test_watcher_event_is_frozen(self):
        """WatcherEvent should be immutable (frozen)."""
        event = WatcherEvent(source_name="test", file_path="/path/file.jsonl")
        with pytest.raises(AttributeError):
            event.source_name = "changed"


class TestSourceWatcher:
    """Tests for SourceWatcher class."""

    @pytest.fixture
    def temp_state_dir(self, tmp_path):
        """Create a temporary directory for state files."""
        return tmp_path / "state"

    def test_init_creates_state_manager(self, temp_state_dir):
        """SourceWatcher should create a SourceStateManager."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=1.0)
        assert watcher.state_manager is not None
        assert watcher.poll_interval == 1.0

    def test_get_sources_with_changes_empty(self, temp_state_dir):
        """get_sources_with_changes returns empty set when no sources."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=1.0)
        sources = watcher.get_sources_with_changes()
        assert sources == set()

    def test_get_sources_with_changes_detects_new_file(self, temp_state_dir):
        """get_sources_with_changes detects when a source has new content."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=1.0)

        # Create a source with an incoming file
        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        with open(incoming, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        # Initialize state for this source (empty state = offset 0)
        watcher.state_manager.save("test_source", watcher.state_manager.load("test_source"))

        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources

    def test_no_changes_when_offset_at_end(self, temp_state_dir):
        """get_sources_with_changes returns empty when offset matches file size."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=1.0)

        # Create a source with an incoming file
        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        with open(incoming, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        file_size = incoming.stat().st_size
        # Set offset to end of file
        watcher.state_manager.update_offset("test_source", incoming.name, file_size)

        sources = watcher.get_sources_with_changes()
        assert "test_source" not in sources

    def test_detects_partial_progress(self, temp_state_dir):
        """get_sources_with_changes detects when file has grown past offset."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=1.0)

        # Create a source with an incoming file
        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Write first message
        with open(incoming, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        first_size = incoming.stat().st_size

        # Set offset to after first message
        watcher.state_manager.update_offset("test_source", incoming.name, first_size)

        # Add more content
        with open(incoming, 'a') as f:
            f.write(json.dumps({"id": 2, "text": "more"}) + '\n')

        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources

    def test_detects_newer_file(self, temp_state_dir):
        """get_sources_with_changes detects when a newer file exists."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=1.0)

        # Create source directory with two incoming files
        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)

        # Create older file (already consumed)
        older = source_dir / "incoming.2026-03-30.jsonl"
        with open(older, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "old"}) + '\n')

        # Mark older as consumed
        watcher.state_manager.update_offset("test_source", older.name, older.stat().st_size)

        # Create newer file
        newer = source_dir / "incoming.2026-03-31.jsonl"
        with open(newer, 'w') as f:
            f.write(json.dumps({"id": 2, "text": "new"}) + '\n')

        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources

    def test_ignores_non_incoming_files(self, temp_state_dir):
        """get_sources_with_changes only checks incoming.*.jsonl files."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=1.0)

        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)

        # Create non-incoming file
        other_file = source_dir / "other.jsonl"
        with open(other_file, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        # Initialize state
        watcher.state_manager.save("test_source", watcher.state_manager.load("test_source"))

        sources = watcher.get_sources_with_changes()
        assert "test_source" not in sources

    def test_watchdog_available_flag(self, temp_state_dir):
        """SourceWatcher should have a WATCHDOG_AVAILABLE flag."""
        watcher = SourceWatcher(state_dir=temp_state_dir)
        # Just check it's a boolean
        assert isinstance(watcher.WATCHDOG_AVAILABLE, bool)

    def test_start_watchdog_returns_bool(self, temp_state_dir):
        """start_watchdog should return bool indicating success."""
        watcher = SourceWatcher(state_dir=temp_state_dir)
        result = watcher.start_watchdog()
        assert isinstance(result, bool)
        # Clean up
        watcher.stop_watchdog()

    def test_stop_watchdog_safe_when_not_started(self, temp_state_dir):
        """stop_watchdog should be safe to call when not started."""
        watcher = SourceWatcher(state_dir=temp_state_dir)
        # Should not raise
        watcher.stop_watchdog()


class TestSourceWatcherAsync:
    """Async tests for SourceWatcher."""

    @pytest.fixture
    def temp_state_dir(self, tmp_path):
        """Create a temporary directory for state files."""
        return tmp_path / "state"

    @pytest.mark.asyncio
    async def test_poll_for_event_detects_new_content(self, temp_state_dir):
        """poll_for_event should detect when new content is added."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=0.1)

        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Initialize state
        watcher.state_manager.save("test_source", watcher.state_manager.load("test_source"))

        # Start with empty file
        incoming.touch()

        async def add_content():
            await asyncio.sleep(0.05)
            with open(incoming, 'w') as f:
                f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        # Run both concurrently
        task = asyncio.create_task(add_content())
        event = await watcher.poll_for_event("test_source", timeout=1.0)
        await task

        assert event is not None
        assert event.source_name == "test_source"
        assert "incoming.2026-03-31.jsonl" in event.file_path

    @pytest.mark.asyncio
    async def test_poll_for_event_timeout_returns_none(self, temp_state_dir):
        """poll_for_event should return None on timeout."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=0.1)

        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Initialize state
        watcher.state_manager.save("test_source", watcher.state_manager.load("test_source"))

        # Empty file, no content added
        incoming.touch()

        event = await watcher.poll_for_event("test_source", timeout=0.2)
        assert event is None

    @pytest.mark.asyncio
    async def test_wait_for_event_with_timeout(self, temp_state_dir):
        """wait_for_event should wait for any source change with timeout."""
        watcher = SourceWatcher(state_dir=temp_state_dir, poll_interval=0.1)

        source_dir = temp_state_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Initialize state
        watcher.state_manager.save("test_source", watcher.state_manager.load("test_source"))

        # Start with empty file
        incoming.touch()

        async def add_content():
            await asyncio.sleep(0.05)
            with open(incoming, 'w') as f:
                f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        task = asyncio.create_task(add_content())
        event = await watcher.wait_for_event(timeout=1.0)
        await task

        assert event is not None
        assert event.source_name == "test_source"


class TestSourceEventHandler:
    """Tests for SourceEventHandler (watchdog handler)."""

    def test_event_handler_exists(self, tmp_path):
        """SourceEventHandler class should be importable."""
        from tele.source_watcher import SourceEventHandler
        assert SourceEventHandler is not None

    def test_event_handler_can_be_created(self, tmp_path):
        """SourceEventHandler should be creatable with a queue."""
        import asyncio
        from tele.source_watcher import SourceEventHandler

        queue = asyncio.Queue()
        sources_dir = tmp_path / "sources"
        handler = SourceEventHandler("test_source", queue, sources_dir)
        assert handler.source_name == "test_source"