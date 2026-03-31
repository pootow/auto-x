"""Tests for source state management."""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from tele.source_state import SourceState, SourceStateManager


class TestSourceState:
    def test_source_state_creation(self):
        """SourceState should be created with required fields."""
        state = SourceState(
            current_file="incoming.2026-03-31.jsonl",
            byte_offset=0,
        )
        assert state.current_file == "incoming.2026-03-31.jsonl"
        assert state.byte_offset == 0
        assert state.last_processed_at is not None

    def test_source_state_to_dict(self):
        """SourceState should serialize to dict."""
        state = SourceState(
            current_file="incoming.2026-03-30.jsonl",
            byte_offset=5000,
            last_processed_at="2026-03-31T10:00:00Z"
        )
        data = state.to_dict()
        assert data["current_file"] == "incoming.2026-03-30.jsonl"
        assert data["byte_offset"] == 5000
        assert data["last_processed_at"] == "2026-03-31T10:00:00Z"

    def test_source_state_from_dict(self):
        """SourceState should deserialize from dict."""
        data = {
            "current_file": "incoming.2026-03-29.jsonl",
            "byte_offset": 1234,
            "last_processed_at": "2026-03-31T09:00:00Z"
        }
        state = SourceState.from_dict(data)
        assert state.current_file == "incoming.2026-03-29.jsonl"
        assert state.byte_offset == 1234

    def test_source_state_new(self):
        """SourceState.new() should create empty state."""
        state = SourceState.new()
        assert state.current_file == ""
        assert state.byte_offset == 0
        assert state.last_processed_at is not None

    def test_source_state_auto_timestamp(self):
        """SourceState should auto-populate last_processed_at."""
        state = SourceState(current_file="test.jsonl", byte_offset=100)
        assert state.last_processed_at is not None
        # Verify it's a valid ISO timestamp
        parsed = datetime.fromisoformat(state.last_processed_at.replace('Z', '+00:00'))
        assert parsed.tzinfo is not None


class TestSourceStateManager:
    """Test cases for SourceStateManager."""

    @pytest.fixture
    def temp_state_dir(self, tmp_path):
        """Create a temporary directory for state files."""
        return tmp_path / "state"

    def test_init_creates_directory(self, temp_state_dir):
        """Test that SourceStateManager creates the sources directory."""
        manager = SourceStateManager(state_dir=temp_state_dir)
        assert manager.sources_dir.exists()

    def test_load_new_source_returns_empty_state(self, temp_state_dir):
        """Loading a non-existent source should return empty state."""
        manager = SourceStateManager(state_dir=temp_state_dir)
        state = manager.load("my_source")
        assert state.current_file == ""
        assert state.byte_offset == 0

    def test_save_and_load_state(self, temp_state_dir):
        """Test saving and loading state for a source."""
        manager = SourceStateManager(state_dir=temp_state_dir)

        # Save state
        state = SourceState(
            current_file="incoming.2026-03-31.jsonl",
            byte_offset=5000,
            last_processed_at="2026-03-31T10:00:00Z"
        )
        success = manager.save("my_source", state)
        assert success is True

        # Load state
        loaded = manager.load("my_source")
        assert loaded.current_file == "incoming.2026-03-31.jsonl"
        assert loaded.byte_offset == 5000
        assert loaded.last_processed_at == "2026-03-31T10:00:00Z"

    def test_update_offset(self, temp_state_dir):
        """Test updating file and offset."""
        manager = SourceStateManager(state_dir=temp_state_dir)

        state = manager.update_offset("my_source", "incoming.2026-03-31.jsonl", 12345)
        assert state.current_file == "incoming.2026-03-31.jsonl"
        assert state.byte_offset == 12345

        # Verify persistence
        loaded = manager.load("my_source")
        assert loaded.byte_offset == 12345

    def test_get_source_dir(self, temp_state_dir):
        """Test source directory path generation."""
        manager = SourceStateManager(state_dir=temp_state_dir)
        source_dir = manager.get_source_dir("my_source")
        assert source_dir.name == "my_source"
        assert source_dir.parent.name == "sources"

    def test_get_state_path(self, temp_state_dir):
        """Test state file path generation."""
        manager = SourceStateManager(state_dir=temp_state_dir)
        state_path = manager.get_state_path("my_source")
        assert state_path.name == "state.json"
        assert state_path.parent.name == "my_source"

    def test_list_sources_empty(self, temp_state_dir):
        """Test listing sources when none exist."""
        manager = SourceStateManager(state_dir=temp_state_dir)
        sources = manager.list_sources()
        assert sources == []

    def test_list_sources(self, temp_state_dir):
        """Test listing existing sources."""
        manager = SourceStateManager(state_dir=temp_state_dir)

        # Create state for multiple sources
        manager.save("source_a", SourceState.new())
        manager.save("source_b", SourceState.new())

        sources = manager.list_sources()
        assert len(sources) == 2
        assert "source_a" in sources
        assert "source_b" in sources

    def test_get_incoming_files_empty(self, temp_state_dir):
        """Test getting incoming files when none exist."""
        manager = SourceStateManager(state_dir=temp_state_dir)
        files = manager.get_incoming_files("my_source")
        assert files == []

    def test_get_incoming_files(self, temp_state_dir):
        """Test getting incoming files sorted by date."""
        manager = SourceStateManager(state_dir=temp_state_dir)

        # Create source directory and incoming files
        source_dir = manager.get_source_dir("my_source")
        source_dir.mkdir(parents=True, exist_ok=True)

        # Create files with different dates
        (source_dir / "incoming.2026-03-29.jsonl").write_text("{}\n")
        (source_dir / "incoming.2026-03-31.jsonl").write_text("{}\n")
        (source_dir / "incoming.2026-03-30.jsonl").write_text("{}\n")
        # Create a non-incoming file that should be ignored
        (source_dir / "state.json").write_text("{}")

        files = manager.get_incoming_files("my_source")
        assert len(files) == 3
        # Should be sorted by name (which includes date)
        assert files[0].name == "incoming.2026-03-29.jsonl"
        assert files[1].name == "incoming.2026-03-30.jsonl"
        assert files[2].name == "incoming.2026-03-31.jsonl"

    def test_load_handles_corrupted_json(self, temp_state_dir):
        """Loading corrupted JSON should return empty state."""
        manager = SourceStateManager(state_dir=temp_state_dir)

        # Write corrupted JSON
        state_path = manager.get_state_path("my_source")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not valid json")

        state = manager.load("my_source")
        assert state.current_file == ""
        assert state.byte_offset == 0

    def test_atomic_save(self, temp_state_dir):
        """Test that save uses atomic write (temp file + rename)."""
        manager = SourceStateManager(state_dir=temp_state_dir)

        state = SourceState(
            current_file="incoming.2026-03-31.jsonl",
            byte_offset=5000,
        )
        manager.save("my_source", state)

        # Verify no temp file remains
        temp_path = manager.get_state_path("my_source").with_suffix('.tmp')
        assert not temp_path.exists()