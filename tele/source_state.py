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