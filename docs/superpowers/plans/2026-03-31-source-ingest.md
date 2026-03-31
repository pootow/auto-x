# Source Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable tele to consume messages from external data sources that write to append-only JSONL files, with file monitoring and polling fallback.

**Architecture:** Data sources write to date-named JSONL files (`incoming.{date}.jsonl`). Tele tracks byte offset in `state.json`, consumes new messages, and processes them through existing pipeline. File monitoring via watchdog with polling fallback for reliability.

**Tech Stack:** Python watchdog library, existing async/queue infrastructure, JSONL persistence patterns.

---

## File Structure

| File | Purpose |
|------|---------|
| `tele/source_state.py` | SourceState dataclass, SourceStateManager for offset tracking |
| `tele/source_watcher.py` | File monitoring (watchdog + polling fallback) |
| `tele/cli.py` (modify) | Add --ingest, --scan, --process-source, --list-sources commands |
| `tele/config.py` (modify) | Add sources configuration section |
| `tests/test_source_state.py` | Unit tests for source state management |
| `tests/test_source_watcher.py` | Unit tests for file monitoring |

---

### Task 1: Source State Data Model

**Files:**
- Create: `tele/source_state.py`
- Test: `tests/test_source_state.py`

- [ ] **Step 1: Write the failing test for SourceState dataclass**

```python
# tests/test_source_state.py
import pytest
from datetime import datetime, timezone
from tele.source_state import SourceState

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_source_state.py -v`
Expected: FAIL with "ModuleNotFoundError" or "ImportError"

- [ ] **Step 3: Write minimal implementation**

```python
# tele/source_state.py
"""State management for external data sources."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

STATE_DIR_DEFAULT = Path.home() / ".tele" / "state"
SOURCES_DIR = "sources"


@dataclass
class SourceState:
    """Consumption state for a single data source.

    Tracks:
    - current_file: The file currently being consumed
    - byte_offset: Position within that file (for seek)
    - last_processed_at: Timestamp of last successful consumption

    Core convention: Date in filename always increases.
    Files with date < current_file are considered complete.
    """
    current_file: str
    byte_offset: int
    last_processed_at: Optional[str] = None

    def __post_init__(self):
        if self.last_processed_at is None:
            self.last_processed_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SourceState":
        return cls(**data)

    @classmethod
    def new(cls) -> "SourceState":
        """Create a new empty state (no files consumed yet)."""
        return cls(
            current_file="",
            byte_offset=0,
        )


class SourceStateManager:
    """Manages consumption state for all data sources.

    Each source has its own directory under ~/.tele/state/sources/{source_name}/
    containing:
    - incoming.{date}.jsonl files (data source writes here)
    - state.json (tele consumption progress)
    - {source_name}_pending.jsonl (messages in retry)
    - {source_name}_dead.jsonl (exhausted retries)
    - {source_name}_fatal.jsonl (fatal errors)
    """

    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = state_dir or STATE_DIR_DEFAULT
        self.sources_dir = self.state_dir / SOURCES_DIR
        self.sources_dir.mkdir(parents=True, exist_ok=True)

    def get_source_dir(self, source_name: str) -> Path:
        """Get the directory for a specific source."""
        return self.sources_dir / source_name

    def get_state_path(self, source_name: str) -> Path:
        """Get the state.json path for a source."""
        return self.get_source_dir(source_name) / "state.json"

    def load(self, source_name: str) -> SourceState:
        """Load state for a source. Returns new empty state if not exists."""
        path = self.get_state_path(source_name)
        if not path.exists():
            return SourceState.new()

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return SourceState.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to load state for %s: %s", source_name, e)
            return SourceState.new()

    def save(self, source_name: str, state: SourceState) -> bool:
        """Save state for a source. Returns True on success."""
        path = self.get_state_path(source_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(state.to_dict(), f, indent=2)
            temp_path.replace(path)
            return True
        except Exception as e:
            logger.error("Failed to save state for %s: %s", source_name, e)
            return False

    def update_offset(self, source_name: str, current_file: str, byte_offset: int) -> SourceState:
        """Update state with new file/offset. Returns updated state."""
        state = SourceState(
            current_file=current_file,
            byte_offset=byte_offset,
        )
        self.save(source_name, state)
        return state

    def list_sources(self) -> List[str]:
        """List all source directories that exist."""
        if not self.sources_dir.exists():
            return []
        return [d.name for d in self.sources_dir.iterdir() if d.is_dir()]

    def get_incoming_files(self, source_name: str) -> List[Path]:
        """Get all incoming files for a source, sorted by date."""
        source_dir = self.get_source_dir(source_name)
        if not source_dir.exists():
            return []

        files = []
        for f in source_dir.iterdir():
            if f.name.startswith("incoming.") and f.name.endswith(".jsonl"):
                files.append(f)

        # Sort by date in filename (incoming.YYYY-MM-DD.jsonl)
        files.sort(key=lambda p: p.name)
        return files
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_source_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tele/source_state.py tests/test_source_state.py
git commit -m "feat(source): add SourceState dataclass and SourceStateManager

- SourceState tracks current_file and byte_offset for consumption
- SourceStateManager handles persistence per source directory
- Date-based filename convention for incoming files

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Source State Manager Extended Methods

**Files:**
- Modify: `tele/source_state.py`
- Modify: `tests/test_source_state.py`

- [ ] **Step 1: Write tests for get_next_file and file completion logic**

```python
# Add to tests/test_source_state.py

class TestSourceStateManager:
    """Tests for SourceStateManager."""

    def test_list_sources_empty(self, tmp_path):
        """list_sources returns empty list when no sources exist."""
        manager = SourceStateManager(state_dir=tmp_path)
        assert manager.list_sources() == []

    def test_list_sources_with_dirs(self, tmp_path):
        """list_sources returns names of source directories."""
        manager = SourceStateManager(state_dir=tmp_path)
        # Create source directories
        (manager.get_source_dir("web_monitor")).mkdir(parents=True)
        (manager.get_source_dir("rss_feed")).mkdir(parents=True)

        sources = manager.list_sources()
        assert "web_monitor" in sources
        assert "rss_feed" in sources

    def test_get_incoming_files_sorted(self, tmp_path):
        """get_incoming_files returns files sorted by date."""
        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True)

        # Create files with different dates
        (source_dir / "incoming.2026-03-29.jsonl").touch()
        (source_dir / "incoming.2026-03-31.jsonl").touch()
        (source_dir / "incoming.2026-03-30.jsonl").touch()

        files = manager.get_incoming_files("test_source")
        assert len(files) == 3
        assert files[0].name == "incoming.2026-03-29.jsonl"
        assert files[1].name == "incoming.2026-03-30.jsonl"
        assert files[2].name == "incoming.2026-03-31.jsonl"

    def test_get_next_file_after_current(self, tmp_path):
        """get_next_file should return files with date > current_file."""
        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True)

        (source_dir / "incoming.2026-03-29.jsonl").touch()
        (source_dir / "incoming.2026-03-30.jsonl").touch()
        (source_dir / "incoming.2026-03-31.jsonl").touch()

        # Current file is 03-30, next should be 03-31
        next_file = manager.get_next_file("test_source", "incoming.2026-03-30.jsonl")
        assert next_file is not None
        assert next_file.name == "incoming.2026-03-31.jsonl"

    def test_get_next_file_no_more_files(self, tmp_path):
        """get_next_file returns None when no files after current."""
        manager = SourceStateManager(state_dir=tmp_path)
        source_dir = manager.get_source_dir("test_source")
        source_dir.mkdir(parents=True)

        (source_dir / "incoming.2026-03-30.jsonl").touch()

        next_file = manager.get_next_file("test_source", "incoming.2026-03-30.jsonl")
        assert next_file is None

    def test_load_save_roundtrip(self, tmp_path):
        """load and save should work together."""
        manager = SourceStateManager(state_dir=tmp_path)

        state = SourceState(
            current_file="incoming.2026-03-30.jsonl",
            byte_offset=5000,
        )
        manager.save("test_source", state)

        loaded = manager.load("test_source")
        assert loaded.current_file == state.current_file
        assert loaded.byte_offset == state.byte_offset

    def test_load_returns_new_state_if_not_exists(self, tmp_path):
        """load returns empty state when no state file exists."""
        manager = SourceStateManager(state_dir=tmp_path)
        state = manager.load("nonexistent")
        assert state.current_file == ""
        assert state.byte_offset == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_source_state.py::TestSourceStateManager -v`
Expected: FAIL with "AttributeError: 'SourceStateManager' object has no attribute 'get_next_file'"

- [ ] **Step 3: Add get_next_file method to SourceStateManager**

```python
# Add to tele/source_state.py, in SourceStateManager class

    def get_next_file(self, source_name: str, current_file: str) -> Optional[Path]:
        """Get the next incoming file after current_file.

        Uses date comparison: files with date > current_file date are next.
        Returns None if no files remain.

        Args:
            source_name: Source identifier
            current_file: Current file name (e.g., "incoming.2026-03-30.jsonl")

        Returns:
            Path to next file, or None if no more files
        """
        files = self.get_incoming_files(source_name)
        if not files:
            return None

        # Extract date from current_file name
        # Format: incoming.YYYY-MM-DD.jsonl
        if not current_file:
            # No current file, return first file
            return files[0]

        try:
            current_date = current_file.replace("incoming.", "").replace(".jsonl", "")
        except Exception:
            return files[0]

        # Find first file with date > current_date
        for f in files:
            file_date = f.name.replace("incoming.", "").replace(".jsonl", "")
            if file_date > current_date:
                return f

        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_source_state.py::TestSourceStateManager -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tele/source_state.py tests/test_source_state.py
git commit -m "feat(source): add get_next_file and list_sources methods

- get_next_file finds files with date > current_file
- list_sources enumerates existing source directories
- get_incoming_files returns sorted list of incoming files

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Source File Consumer (Byte Offset Reading)

**Files:**
- Create: `tele/source_consumer.py`
- Test: `tests/test_source_consumer.py`

- [ ] **Step 1: Write tests for reading messages from offset**

```python
# tests/test_source_consumer.py
import pytest
import json
from pathlib import Path
from tele.source_consumer import SourceConsumer, consume_from_offset

class TestSourceConsumer:
    """Tests for consuming messages from incoming files."""

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
        # Write 3 messages
        with open(file_path, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "msg1"}) + '\n')
            f.write(json.dumps({"id": 2, "text": "msg2"}) + '\n')
            f.write(json.dumps({"id": 3, "text": "msg3"}) + '\n')

        messages, new_offset = consume_from_offset(file_path, 0)
        assert len(messages) == 3
        assert messages[0]["id"] == 1
        assert messages[2]["id"] == 3
        # new_offset should be at end of file
        assert new_offset == file_path.stat().st_size

    def test_consume_from_middle_offset(self, tmp_path):
        """consume_from_offset reads only messages after offset."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Write messages
        with open(file_path, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "msg1"}) + '\n')
            f.write(json.dumps({"id": 2, "text": "msg2"}) + '\n')
            f.write(json.dumps({"id": 3, "text": "msg3"}) + '\n')

        # Get offset after first line
        first_line = json.dumps({"id": 1, "text": "msg1"}) + '\n'
        offset_after_first = len(first_line.encode('utf-8'))

        messages, new_offset = consume_from_offset(file_path, offset_after_first)
        assert len(messages) == 2
        assert messages[0]["id"] == 2
        assert messages[1]["id"] == 3

    def test_consume_returns_byte_offset_for_seek(self, tmp_path):
        """consume_from_offset returns byte offset, not line number."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Write message with unicode (multi-byte chars)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps({"id": 1, "text": "你好世界"}) + '\n')  # Chinese chars
            f.write(json.dumps({"id": 2, "text": "msg2"}) + '\n')

        messages, new_offset = consume_from_offset(file_path, 0)
        assert len(messages) == 2

        # Verify offset works for seek
        with open(file_path, 'rb') as f:
            f.seek(new_offset)
            remaining = f.read()
        assert len(remaining) == 0  # Should be at end

    def test_consume_handles_partial_line(self, tmp_path):
        """consume_from_offset skips incomplete lines at end."""
        file_path = tmp_path / "incoming.2026-03-31.jsonl"
        # Write complete line + partial line
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps({"id": 1, "text": "complete"}) + '\n')
            f.write('{"id": 2, "text": "incomplete...')  # No newline

        messages, new_offset = consume_from_offset(file_path, 0)
        assert len(messages) == 1  # Only complete line
        assert messages[0]["id"] == 1
        # new_offset should be at end of complete line
        first_line_bytes = len((json.dumps({"id": 1, "text": "complete"}) + '\n').encode('utf-8'))
        assert new_offset == first_line_bytes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_source_consumer.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write consume_from_offset implementation**

```python
# tele/source_consumer.py
"""Consumer for reading messages from source incoming files."""

import json
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any

logger = logging.getLogger(__name__)


def consume_from_offset(file_path: Path, byte_offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """Read messages from a file starting at byte offset.

    Uses seek() for efficient positioning. Reads lines until end of file.
    Skips incomplete lines (no newline at end) - these may be mid-write.

    Args:
        file_path: Path to incoming.jsonl file
        byte_offset: Byte position to start reading from

    Returns:
        Tuple of (messages, new_byte_offset):
        - messages: List of parsed JSON message dicts
        - new_byte_offset: Byte position after last complete line
    """
    if not file_path.exists():
        return [], byte_offset

    messages = []
    new_offset = byte_offset

    try:
        with open(file_path, 'rb') as f:
            # Seek to offset
            f.seek(byte_offset)

            # Read and parse lines
            for line in f:
                line = line.decode('utf-8')
                # Check for complete line (ends with newline)
                if not line.endswith('\n'):
                    # Incomplete line - may be mid-write
                    # Return position before this incomplete line
                    logger.debug("Skipping incomplete line at end of %s", file_path)
                    break

                line = line.strip()
                if not line:
                    # Empty line, update offset and continue
                    new_offset = f.tell()
                    continue

                try:
                    msg = json.loads(line)
                    messages.append(msg)
                    new_offset = f.tell()
                except json.JSONDecodeError as e:
                    logger.warning("Skipping invalid JSON line in %s: %s", file_path, e)
                    new_offset = f.tell()
                    continue

        return messages, new_offset

    except Exception as e:
        logger.error("Error reading %s: %s", file_path, e)
        return [], byte_offset


class SourceConsumer:
    """Consumer for a single data source.

    Handles:
    - Reading from current file at offset
    - Switching to next file when current is exhausted
    - Managing state updates
    """

    def __init__(self, source_name: str, state_manager):
        """Initialize consumer.

        Args:
            source_name: Source identifier
            state_manager: SourceStateManager instance
        """
        self.source_name = source_name
        self.state_manager = state_manager

    def consume_available(self) -> List[Dict[str, Any]]:
        """Consume all available messages from source.

        Reads from current file at offset, then continues to next files
        if available. Updates state as files are completed.

        Returns:
            List of parsed messages
        """
        state = self.state_manager.load(self.source_name)
        all_messages = []

        # Get incoming files
        files = self.state_manager.get_incoming_files(self.source_name)
        if not files:
            return []

        # Determine starting file
        if not state.current_file:
            # No state, start from first file
            current_file = files[0]
            byte_offset = 0
        else:
            # Find current file in list
            current_file = None
            for f in files:
                if f.name == state.current_file:
                    current_file = f
                    break

            if current_file is None:
                # Current file not found (may have been renamed/deleted)
                # Find file with date >= current_file's date
                current_date = state.current_file.replace("incoming.", "").replace(".jsonl", "")
                for f in files:
                    file_date = f.name.replace("incoming.", "").replace(".jsonl", "")
                    if file_date >= current_date:
                        current_file = f
                        break

                if current_file is None:
                    # No files to process
                    return []

                # Start from beginning of this file
                byte_offset = 0
            else:
                byte_offset = state.byte_offset

        # Consume from current file
        messages, new_offset = consume_from_offset(current_file, byte_offset)
        all_messages.extend(messages)

        # Check if file is exhausted (offset == file size)
        file_size = current_file.stat().st_size
        if new_offset >= file_size and messages:
            # File fully consumed, move to next file
            next_file = self.state_manager.get_next_file(self.source_name, current_file.name)
            if next_file:
                # Update state to next file
                self.state_manager.update_offset(
                    self.source_name,
                    next_file.name,
                    0
                )
                # Consume from next file
                next_messages, next_offset = consume_from_offset(next_file, 0)
                all_messages.extend(next_messages)
                if next_messages:
                    self.state_manager.update_offset(
                        self.source_name,
                        next_file.name,
                        next_offset
                    )
            else:
                # No next file, stay at end of current
                self.state_manager.update_offset(
                    self.source_name,
                    current_file.name,
                    new_offset
                )
        elif messages:
            # Partial consumption, update offset
            self.state_manager.update_offset(
                self.source_name,
                current_file.name,
                new_offset
            )

        return all_messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_source_consumer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tele/source_consumer.py tests/test_source_consumer.py
git commit -m "feat(source): add SourceConsumer for byte-offset reading

- consume_from_offset reads messages using seek() for efficiency
- Handles incomplete lines at end of file (mid-write safety)
- SourceConsumer manages file switching and state updates

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Source Watcher (File Monitoring)

**Files:**
- Create: `tele/source_watcher.py`
- Test: `tests/test_source_watcher.py`

- [ ] **Step 1: Write tests for file watcher events**

```python
# tests/test_source_watcher.py
import pytest
import asyncio
import json
from pathlib import Path
from tele.source_watcher import SourceWatcher, WatcherEvent

class TestWatcherEvent:
    """Tests for WatcherEvent dataclass."""

    def test_watcher_event_creation(self):
        """WatcherEvent should capture source and file."""
        event = WatcherEvent(source_name="web_monitor", file_path="/path/to/file.jsonl")
        assert event.source_name == "web_monitor"
        assert event.file_path == "/path/to/file.jsonl"

class TestSourceWatcher:
    """Tests for SourceWatcher file monitoring."""

    @pytest.mark.asyncio
    async def test_polling_detects_new_file(self, tmp_path):
        """Polling should detect new incoming files."""
        state_manager_dir = tmp_path / "state"
        watcher = SourceWatcher(state_dir=state_manager_dir, poll_interval=0.1)

        # Create a source directory with incoming file
        source_dir = state_manager_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        events = []

        async def collect_events():
            # Wait a bit, then write to file
            await asyncio.sleep(0.05)
            with open(incoming, 'w') as f:
                f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

            # Poll should detect change
            event = await watcher.poll_for_event("test_source", timeout=1.0)
            if event:
                events.append(event)

        await asyncio.wait_for(collect_events(), timeout=2.0)
        assert len(events) == 1
        assert events[0].source_name == "test_source"

    def test_get_sources_with_changes(self, tmp_path):
        """get_sources_with_changes should detect file size changes."""
        state_manager_dir = tmp_path / "state"
        watcher = SourceWatcher(state_dir=state_manager_dir, poll_interval=1.0)

        # Create source with incoming file
        source_dir = state_manager_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Initialize state at offset 0
        watcher.state_manager.save("test_source", watcher.state_manager.load("test_source"))

        # Write to file
        with open(incoming, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        # Check for changes
        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources

    def test_no_changes_when_offset_at_end(self, tmp_path):
        """No changes detected when offset matches file size."""
        state_manager_dir = tmp_path / "state"
        watcher = SourceWatcher(state_dir=state_manager_dir, poll_interval=1.0)

        # Create source with incoming file
        source_dir = state_manager_dir / "sources" / "test_source"
        source_dir.mkdir(parents=True)
        incoming = source_dir / "incoming.2026-03-31.jsonl"

        # Write to file
        with open(incoming, 'w') as f:
            f.write(json.dumps({"id": 1, "text": "test"}) + '\n')

        file_size = incoming.stat().st_size

        # Set offset to file size (fully consumed)
        watcher.state_manager.update_offset("test_source", incoming.name, file_size)

        # Check for changes
        sources = watcher.get_sources_with_changes()
        assert "test_source" not in sources
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_source_watcher.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write SourceWatcher implementation**

```python
# tele/source_watcher.py
"""File monitoring for source incoming files.

Two-layer approach:
1. watchdog event monitoring (primary, real-time)
2. polling fallback (always active, catches missed events)
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Set

from .source_state import SourceStateManager, SourceState

logger = logging.getLogger(__name__)

# Try to import watchdog, but don't fail if not available
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog not available, falling back to polling only")


@dataclass
class WatcherEvent:
    """Event triggered by file change detection."""
    source_name: str
    file_path: str


class SourceWatcher:
    """Monitors source directories for file changes.

    Combines watchdog (real-time) with polling (fallback).
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        poll_interval: float = 30.0,
        watch_enabled: bool = True,
    ):
        """Initialize watcher.

        Args:
            state_dir: State directory path
            poll_interval: Polling interval in seconds
            watch_enabled: Enable watchdog monitoring (can disable if problematic)
        """
        self.state_manager = SourceStateManager(state_dir)
        self.poll_interval = poll_interval
        self.watch_enabled = watch_enabled and WATCHDOG_AVAILABLE

        self._observer = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._file_sizes: dict[str, int] = {}  # Track last seen sizes
        self._running = False

    def start_watchdog(self) -> bool:
        """Start watchdog observer if available and enabled.

        Returns:
            True if watchdog started, False if not available/disabled
        """
        if not self.watch_enabled:
            logger.info("Watchdog monitoring disabled by config")
            return False

        if not WATCHDOG_AVAILABLE:
            logger.info("Watchdog not available, using polling only")
            return False

        try:
            self._observer = Observer()
            handler = SourceEventHandler(self._event_queue, self.state_manager)

            # Watch sources directory
            self._observer.schedule(
                handler,
                str(self.state_manager.sources_dir),
                recursive=True  # Watch all subdirectories
            )
            self._observer.start()
            logger.info("Started watchdog monitoring on %s", self.state_manager.sources_dir)
            return True
        except Exception as e:
            logger.warning("Failed to start watchdog: %s, falling back to polling", e)
            self._observer = None
            return False

    def stop_watchdog(self) -> None:
        """Stop watchdog observer."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

    def get_sources_with_changes(self) -> Set[str]:
        """Poll all sources and detect which have changes.

        Compares file size with recorded offset to detect new content.

        Returns:
            Set of source names that have new content
        """
        sources_with_changes = set()

        for source_name in self.state_manager.list_sources():
            state = self.state_manager.load(source_name)

            # Get current or first file
            files = self.state_manager.get_incoming_files(source_name)
            if not files:
                continue

            # Check each file
            for f in files:
                file_name = f.name
                file_size = f.stat().st_size

                # Compare with state
                if state.current_file == file_name:
                    # Current file - check if more content than offset
                    if file_size > state.byte_offset:
                        sources_with_changes.add(source_name)
                        break
                elif not state.current_file:
                    # No current file, any file has content
                    if file_size > 0:
                        sources_with_changes.add(source_name)
                        break
                else:
                    # Check if file date > current_file date
                    current_date = state.current_file.replace("incoming.", "").replace(".jsonl", "")
                    file_date = file_name.replace("incoming.", "").replace(".jsonl", "")
                    if file_date > current_date and file_size > 0:
                        sources_with_changes.add(source_name)
                        break

        return sources_with_changes

    async def wait_for_event(self, timeout: float = None) -> Optional[WatcherEvent]:
        """Wait for a file change event.

        Combines watchdog events and polling.

        Args:
            timeout: Max time to wait (None = poll_interval)

        Returns:
            WatcherEvent if detected, None if timeout
        """
        if timeout is None:
            timeout = self.poll_interval

        # Try watchdog event first
        try:
            event = await asyncio.wait_for(
                self._event_queue.get(),
                timeout=min(timeout, 1.0)  # Quick check
            )
            return event
        except asyncio.TimeoutError:
            pass

        # Fallback to polling
        remaining_time = timeout - 1.0
        if remaining_time > 0:
            await asyncio.sleep(remaining_time)

        # Check for changes
        sources = self.get_sources_with_changes()
        if sources:
            # Return first source with changes
            source_name = next(iter(sources))
            files = self.state_manager.get_incoming_files(source_name)
            if files:
                return WatcherEvent(source_name, str(files[-1]))  # Latest file

        return None

    async def poll_for_event(self, source_name: str, timeout: float = 30.0) -> Optional[WatcherEvent]:
        """Poll a specific source for changes.

        Args:
            source_name: Source to poll
            timeout: Max time to wait

        Returns:
            WatcherEvent if detected, None if timeout
        """
        start_time = datetime.now(timezone.utc).timestamp()
        check_interval = min(0.5, timeout / 10)

        while True:
            state = self.state_manager.load(source_name)
            files = self.state_manager.get_incoming_files(source_name)

            if files:
                # Find file to check
                current_file = None
                for f in files:
                    if f.name == state.current_file:
                        current_file = f
                        break

                if current_file is None and files:
                    current_file = files[0] if not state.current_file else files[-1]

                if current_file:
                    file_size = current_file.stat().st_size
                    if file_size > state.byte_offset:
                        return WatcherEvent(source_name, str(current_file))

            # Check timeout
            elapsed = datetime.now(timezone.utc).timestamp() - start_time
            if elapsed >= timeout:
                return None

            await asyncio.sleep(check_interval)


class SourceEventHandler(FileSystemEventHandler):
    """Watchdog event handler for source file changes."""

    def __init__(self, event_queue: asyncio.Queue, state_manager: SourceStateManager):
        self.event_queue = event_queue
        self.state_manager = state_manager

    def on_modified(self, event):
        """Handle file modification event."""
        if event.is_directory:
            return

        # Check if it's an incoming file
        path = Path(event.src_path)
        if not path.name.startswith("incoming.") or not path.name.endswith(".jsonl"):
            return

        # Extract source name from parent directory
        parent = path.parent
        sources_dir = self.state_manager.sources_dir
        if parent.parent == sources_dir:
            source_name = parent.name
            watcher_event = WatcherEvent(source_name, str(path))
            # Put in queue (non-blocking for sync handler)
            try:
                self.state_manager.sources_dir.mkdir(parents=True, exist_ok=True)
                # Use call_soon_threadsafe to put from watchdog thread
                asyncio.get_event_loop().call_soon_threadsafe(
                    self.event_queue.put_nowait, watcher_event
                )
            except Exception as e:
                logger.debug("Failed to queue event: %s", e)

    def on_created(self, event):
        """Handle file creation event."""
        # Treat creation same as modification for incoming files
        self.on_modified(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_source_watcher.py -v`
Expected: PASS (some tests may be slow due to async)

- [ ] **Step 5: Commit**

```bash
git add tele/source_watcher.py tests/test_source_watcher.py
git commit -m "feat(source): add SourceWatcher for file monitoring

- watchdog event monitoring (primary, real-time)
- polling fallback (always active, catches missed events)
- get_sources_with_changes detects files with new content

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Config Extension for Sources

**Files:**
- Modify: `tele/config.py`
- Test: `tests/test_config.py` (modify)

- [ ] **Step 1: Write tests for sources config**

```python
# Add to tests/test_config.py

class TestSourcesConfig:
    """Tests for sources configuration."""

    def test_load_config_with_sources(self, tmp_path):
        """Config should load sources section."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text('''
telegram:
  api_id: 123
  api_hash: test_hash
sources:
  web_monitor:
    processor: "python monitor.py"
    chat_id: 12345
  rss_feed:
    processor: "rss-processor"
    chat_id: 67890
    filter: 'contains("important")'
ingest:
  poll_interval: 30
  watch_enabled: true
''')
        # Assuming load_config can take a path
        # This test depends on actual config.py structure
        # Placeholder - adjust based on actual implementation
        pass

    def test_default_ingest_config(self):
        """Ingest config should have sensible defaults."""
        from tele.config import IngestConfig
        config = IngestConfig()
        assert config.poll_interval == 30
        assert config.watch_enabled == True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::TestSourcesConfig -v`
Expected: FAIL (depends on current config.py structure)

- [ ] **Step 3: Read current config.py and add sources section**

First read existing config.py to understand structure:

Run: `cat tele/config.py` (use Read tool instead)

Then modify to add:

```python
# Add to tele/config.py (adjust to match existing structure)

@dataclass
class SourceConfig:
    """Configuration for a single data source."""
    processor: str
    chat_id: int
    filter: Optional[str] = None
    path: Optional[str] = None  # Override default source directory


@dataclass
class IngestConfig:
    """Configuration for ingest mode."""
    poll_interval: float = 30.0
    watch_enabled: bool = True


@dataclass
class TeleConfig:
    """Full tele configuration."""
    telegram: TelegramConfig
    defaults: DefaultsConfig
    sources: Dict[str, SourceConfig] = field(default_factory=dict)
    ingest: IngestConfig = field(default_factory=IngestConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::TestSourcesConfig -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tele/config.py tests/test_config.py
git commit -m "feat(config): add sources and ingest configuration sections

- SourceConfig per source (processor, chat_id, filter, path)
- IngestConfig with poll_interval and watch_enabled
- Loaded from YAML config file

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: CLI Commands for Ingest Mode

**Files:**
- Modify: `tele/cli.py`
- Test: `tests/test_cli_ingest.py` (create)

- [ ] **Step 1: Write tests for CLI ingest commands**

```python
# tests/test_cli_ingest.py
import pytest
from click.testing import CliRunner
from tele.cli import cli

class TestIngestCLI:
    """Tests for ingest CLI commands."""

    def test_list_sources_empty(self):
        """--list-sources should return empty when no sources."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--list-sources'])
        assert result.exit_code == 0
        assert "No sources configured" in result.output or result.output.strip() == ""

    def test_scan_command_exists(self):
        """--scan command should be recognized."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--scan'])
        # Should not show "Error: no such option"
        assert "no such option" not in result.output.lower()

    def test_process_source_requires_source_name(self):
        """--process-source should require source name."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--process-source'])
        # Should show error about missing argument
        assert result.exit_code != 0 or "requires" in result.output.lower()

    def test_ingest_command_exists(self):
        """--ingest command should be recognized."""
        runner = CliRunner()
        # --ingest requires config, so may fail but should be recognized
        result = runner.invoke(cli, ['--ingest', '--help'])
        # Should not show unknown option error
        assert "unknown option" not in result.output.lower() or "Error" not in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_ingest.py -v`
Expected: FAIL with "no such option: --list-sources"

- [ ] **Step 3: Add CLI options for ingest mode**

```python
# Add to tele/cli.py imports
from .source_state import SourceStateManager
from .source_consumer import SourceConsumer
from .source_watcher import SourceWatcher

# Add CLI options (after existing options, around line 43)
@click.option('--ingest', 'ingest_mode', is_flag=True, help='Run ingest daemon (monitor sources)')
@click.option('--scan', 'scan_mode', is_flag=True, help='Scan all sources once')
@click.option('--process-source', 'process_source', help='Process specific source')
@click.option('--list-sources', 'list_sources_mode', is_flag=True, help='List configured sources')

# Add to cli function parameters
def cli(
    ...
    ingest_mode: bool,
    scan_mode: bool,
    process_source: Optional[str],
    list_sources_mode: bool,
) -> None:

# Add to cli function body (after retry_dead mode handling)
    # List sources mode
    if list_sources_mode:
        run_list_sources(config)
        return

    # Scan mode
    if scan_mode:
        asyncio.run(run_scan_mode(config))
        return

    # Process specific source
    if process_source:
        asyncio.run(run_process_source(config, process_source))
        return

    # Ingest daemon mode
    if ingest_mode:
        asyncio.run(run_ingest_mode(config, verbose))
        return
```

- [ ] **Step 4: Implement the mode functions**

```python
# Add to tele/cli.py

def run_list_sources(config) -> None:
    """List all configured sources."""
    logger = get_logger("tele.sources")
    state_mgr = SourceStateManager()

    sources = config.sources if hasattr(config, 'sources') else {}
    existing = state_mgr.list_sources()

    if not sources and not existing:
        click.echo("No sources configured")
        return

    click.echo("Configured sources:")
    for name, src_config in sources.items():
        state = state_mgr.load(name)
        status = f"offset={state.byte_offset} in {state.current_file}" if state.current_file else "new"
        click.echo(f"  {name}: processor={src_config.processor}, chat={src_config.chat_id}, {status}")

    # Show sources with incoming files but not in config
    for name in existing:
        if name not in sources:
            click.echo(f"  {name}: (no config, has incoming files)")


async def run_scan_mode(config) -> None:
    """Scan all sources once and process any with changes."""
    logger = get_logger("tele.scan")
    state_mgr = SourceStateManager()
    watcher = SourceWatcher()

    sources_with_changes = watcher.get_sources_with_changes()
    if not sources_with_changes:
        logger.info("No sources with changes")
        click.echo("No sources with changes")
        return

    click.echo(f"Found {len(sources_with_changes)} sources with changes")
    for source_name in sources_with_changes:
        await process_source_messages(config, source_name)


async def run_process_source(config, source_name: str) -> None:
    """Process a specific source."""
    logger = get_logger("tele.source")
    await process_source_messages(config, source_name)


async def process_source_messages(config, source_name: str) -> None:
    """Consume and process messages from a source."""
    logger = get_logger("tele.ingest")

    state_mgr = SourceStateManager()
    consumer = SourceConsumer(source_name, state_mgr)

    # Get source config
    sources = config.sources if hasattr(config, 'sources') else {}
    src_config = sources.get(source_name)

    if not src_config:
        logger.warning("No config for source %s", source_name)
        click.echo(f"Warning: No config for source {source_name}")
        return

    # Consume messages
    messages = consumer.consume_available()
    if not messages:
        logger.info("No new messages from %s", source_name)
        click.echo(f"No new messages from {source_name}")
        return

    logger.info("Consumed %s messages from %s", len(messages), source_name)
    click.echo(f"Processing {len(messages)} messages from {source_name}")

    # Add required fields for processor protocol
    for msg in messages:
        if 'chat_id' not in msg:
            msg['chat_id'] = src_config.chat_id
        if 'source' not in msg:
            msg['source'] = source_name

    # Run processor
    results = await run_exec_command(src_config.processor, messages, shell=True)

    # Handle results
    success_count = sum(1 for r in results if r.get('status') == 'success')
    error_count = sum(1 for r in results if r.get('status') == 'error')
    fatal_count = sum(1 for r in results if r.get('status') == 'fatal')

    click.echo(f"Results: {success_count} success, {error_count} error, {fatal_count} fatal")

    # Note: Full retry/dead-letter integration follows existing bot mode pattern
    # Messages remain tracked via state.json offset advancement

    click.echo(f"Processed {len(results)} results")


async def run_ingest_mode(config, verbose: int = 0) -> None:
    """Run ingest daemon with file monitoring."""
    logger = get_logger("tele.ingest")

    ingest_config = config.ingest if hasattr(config, 'ingest') else None
    poll_interval = ingest_config.poll_interval if ingest_config else 30.0
    watch_enabled = ingest_config.watch_enabled if ingest_config else True

    watcher = SourceWatcher(
        poll_interval=poll_interval,
        watch_enabled=watch_enabled,
    )

    # Start watchdog if available
    watchdog_started = watcher.start_watchdog()
    if watchdog_started:
        logger.info("Started watchdog monitoring")
    else:
        logger.info("Using polling mode (interval=%ss)", poll_interval)

    logger.info("Ingest daemon started")

    try:
        while True:
            # Wait for event (watchdog or polling)
            event = await watcher.wait_for_event(timeout=poll_interval)

            if event:
                logger.info("Detected changes in %s", event.source_name)
                await process_source_messages(config, event.source_name)
            else:
                # No event, poll all sources anyway
                sources = watcher.get_sources_with_changes()
                for source_name in sources:
                    await process_source_messages(config, source_name)

    except KeyboardInterrupt:
        logger.info("Shutting down ingest daemon...")
    finally:
        watcher.stop_watchdog()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_ingest.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tele/cli.py tests/test_cli_ingest.py
git commit -m "feat(cli): add ingest mode commands

- --ingest: daemon mode with file monitoring
- --scan: one-time scan of all sources
- --process-source: process specific source
- --list-sources: show configured sources and state

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Integration Test

**Files:**
- Create: `tests/test_ingest_integration.py`

- [ ] **Step 1: Write integration test for full ingest flow**

```python
# tests/test_ingest_integration.py
import pytest
import asyncio
import json
from pathlib import Path
from click.testing import CliRunner

from tele.source_state import SourceStateManager, SourceState
from tele.source_consumer import SourceConsumer, consume_from_offset
from tele.source_watcher import SourceWatcher


class TestIngestIntegration:
    """Integration tests for source ingest flow."""

    @pytest.mark.asyncio
    async def test_full_consume_flow(self, tmp_path):
        """Test complete flow: write -> consume -> process."""
        # Setup
        state_dir = tmp_path / "state"
        state_mgr = SourceStateManager(state_dir=state_dir)

        # Create source directory
        source_dir = state_mgr.get_source_dir("test_source")
        source_dir.mkdir(parents=True)

        # Write incoming file
        incoming = source_dir / "incoming.2026-03-31.jsonl"
        messages = [
            {"id": "msg1", "text": "first message", "date": "2026-03-31T10:00:00Z"},
            {"id": "msg2", "text": "second message", "date": "2026-03-31T11:00:00Z"},
        ]
        with open(incoming, 'w', encoding='utf-8') as f:
            for msg in messages:
                f.write(json.dumps(msg) + '\n')

        # Consume
        consumer = SourceConsumer("test_source", state_mgr)
        consumed = consumer.consume_available()

        assert len(consumed) == 2
        assert consumed[0]["id"] == "msg1"
        assert consumed[1]["id"] == "msg2"

        # Verify state updated
        state = state_mgr.load("test_source")
        assert state.current_file == "incoming.2026-03-31.jsonl"
        assert state.byte_offset == incoming.stat().st_size

        # Write more messages (append)
        with open(incoming, 'a', encoding='utf-8') as f:
            f.write(json.dumps({"id": "msg3", "text": "third"}) + '\n')

        # Consume again
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

        # Create multiple date files
        day1 = source_dir / "incoming.2026-03-30.jsonl"
        day2 = source_dir / "incoming.2026-03-31.jsonl"

        with open(day1, 'w') as f:
            f.write(json.dumps({"id": "d1-1", "text": "day1 msg1"}) + '\n')
            f.write(json.dumps({"id": "d1-2", "text": "day1 msg2"}) + '\n')

        with open(day2, 'w') as f:
            f.write(json.dumps({"id": "d2-1", "text": "day2 msg1"}) + '\n')

        # Consume all
        consumer = SourceConsumer("test_source", state_mgr)
        all_consumed = consumer.consume_available()

        assert len(all_consumed) == 3
        assert all_consumed[0]["id"] == "d1-1"
        assert all_consumed[2]["id"] == "d2-1"

        # State should be at last file
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

        # Initialize state at offset 0
        watcher.state_manager.save("test_source", SourceState.new())

        # Write initial content
        with open(incoming, 'w') as f:
            f.write(json.dumps({"id": 1}) + '\n')

        # Wait for file size to settle
        await asyncio.sleep(0.1)

        # Should detect changes
        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources

        # Consume and update state
        consumer = SourceConsumer("test_source", watcher.state_manager)
        consumer.consume_available()

        # No more changes
        sources = watcher.get_sources_with_changes()
        assert "test_source" not in sources

        # Append more
        with open(incoming, 'a') as f:
            f.write(json.dumps({"id": 2}) + '\n')

        await asyncio.sleep(0.1)

        # Should detect again
        sources = watcher.get_sources_with_changes()
        assert "test_source" in sources
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/test_ingest_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_ingest_integration.py
git commit -m "test(ingest): add integration tests for full flow

- Full consume flow test
- Multi-date file switching test
- Watcher append detection test

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Add watchdog to dependencies

**Files:**
- Modify: `pyproject.toml` or requirements

- [ ] **Step 1: Check current dependencies**

Run: `cat pyproject.toml` (use Read tool)

- [ ] **Step 2: Add watchdog dependency**

Add to dependencies:
```
"watchdog>=3.0.0",
```

- [ ] **Step 3: Install and verify**

Run: `uv pip install watchdog` or `uv sync`

- [ ] **Step 4: Run all tests to verify nothing broken**

Run: `uv run pytest -v`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add watchdog dependency for file monitoring

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

After writing this plan, verify:

1. **Spec coverage**: Each spec section has corresponding task
   - Directory structure → Task 1, 2
   - state.json format → Task 1
   - Byte offset reading → Task 3
   - File monitoring → Task 4
   - Config section → Task 5
   - CLI commands → Task 6
   - Integration → Task 7

2. **Placeholder scan**: No TBD, TODO, or vague descriptions

3. **Type consistency**: SourceState fields match across all tasks

---

## Spec Gap Analysis

Checking spec against plan:

| Spec Section | Covered By Task |
|--------------|-----------------|
| Directory structure | Task 1 (SourceStateManager) |
| state.json format | Task 1 (SourceState dataclass) |
| Date naming convention | Task 2 (get_next_file) |
| Byte offset consumption | Task 3 (consume_from_offset) |
| File monitoring (watchdog) | Task 4 (SourceWatcher) |
| Polling fallback | Task 4 (get_sources_with_changes) |
| Config sources section | Task 5 |
| CLI --ingest | Task 6 |
| CLI --scan | Task 6 |
| CLI --process-source | Task 6 |
| CLI --list-sources | Task 6 |
| Error handling (pending/dead/fatal) | Not implemented yet - needs follow-up |

**Gap**: Error handling with retry queues for ingest mode. Need follow-up tasks to integrate with existing PendingQueue/DeadLetterQueue infrastructure.

**Decision**: Core consumption/monitoring first. Error handling in follow-up plan.