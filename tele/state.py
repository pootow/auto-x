"""State management for incremental message processing."""

import json
import os
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ChatState:
    """State for a single chat's incremental processing."""
    last_message_id: int
    last_processed_at: str
    chat_id: Optional[int] = None

    @classmethod
    def new(cls, chat_id: Optional[int] = None) -> "ChatState":
        """Create a new empty state.

        Args:
            chat_id: Optional chat ID

        Returns:
            New ChatState instance
        """
        return cls(
            last_message_id=0,
            last_processed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            chat_id=chat_id,
        )


class StateManager:
    """Manages incremental processing state."""

    def __init__(self, state_dir: Optional[str] = None):
        """Initialize state manager.

        Args:
            state_dir: Directory for state files (defaults to ~/.tele/state/)
        """
        if state_dir is None:
            state_dir = os.path.expanduser("~/.tele/state")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _get_state_path(self, chat_id: int | str) -> Path:
        """Get the path to a chat's state file.

        Args:
            chat_id: Chat ID

        Returns:
            Path to state file
        """
        # Use string representation for chat_id to handle both int and str
        return self.state_dir / f"{chat_id}.json"

    def load(self, chat_id: int | str) -> ChatState:
        """Load state for a chat.

        Args:
            chat_id: Chat ID

        Returns:
            ChatState instance (new if no state exists)
        """
        path = self._get_state_path(chat_id)
        if not path.exists():
            return ChatState.new(chat_id=int(chat_id) if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit() else None)

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ChatState(**data)
        except (json.JSONDecodeError, KeyError):
            return ChatState.new(chat_id=int(chat_id) if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit() else None)

    def save(self, chat_id: int | str, state: ChatState) -> None:
        """Save state for a chat.

        Args:
            chat_id: Chat ID
            state: ChatState to save
        """
        path = self._get_state_path(chat_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(state), f, indent=2)

    def update(self, chat_id: int | str, last_message_id: int) -> ChatState:
        """Update state with a new last_message_id.

        Args:
            chat_id: Chat ID
            last_message_id: New last message ID

        Returns:
            Updated ChatState
        """
        state = ChatState(
            last_message_id=last_message_id,
            last_processed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            chat_id=int(chat_id) if isinstance(chat_id, str) and chat_id.lstrip('-').isdigit() else None,
        )
        self.save(chat_id, state)
        return state

    def clear(self, chat_id: int | str) -> None:
        """Clear state for a chat.

        Args:
            chat_id: Chat ID
        """
        path = self._get_state_path(chat_id)
        if path.exists():
            path.unlink()


class BotStateManager:
    """Manages bot mode state (offset-based)."""

    def __init__(self, state_dir: Optional[str] = None):
        """Initialize bot state manager.

        Args:
            state_dir: Directory for state files (defaults to ~/.tele/state/)
        """
        if state_dir is None:
            state_dir = os.path.expanduser("~/.tele/state")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, chat_id: int) -> Path:
        """Get the path to a chat's bot state file.

        Args:
            chat_id: Chat ID

        Returns:
            Path to state file
        """
        return self.state_dir / f"bot_{chat_id}.json"

    def load(self, chat_id: int) -> dict:
        """Load bot state for a chat.

        Args:
            chat_id: Chat ID

        Returns:
            dict with last_update_id (0 if no state) and last_processed_at
        """
        path = self._state_path(chat_id)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, KeyError):
                pass
        return {"last_update_id": 0, "last_processed_at": None}

    def save(self, chat_id: int, update_id: int) -> None:
        """Save bot state after successful processing.

        Args:
            chat_id: Chat ID
            update_id: Last processed update ID
        """
        path = self._state_path(chat_id)
        state = {
            "last_update_id": update_id,
            "last_processed_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)


@dataclass
class PendingMessage:
    """A message waiting to be processed."""
    message_id: int
    chat_id: int
    update_id: int
    message: dict
    retry_count: int = 0
    last_attempt: Optional[str] = None


class PendingQueue:
    """Manages pending messages for crash recovery."""

    def __init__(self, chat_id: int, state_dir: Optional[str] = None):
        """Initialize pending queue.

        Args:
            chat_id: Chat ID this queue is for
            state_dir: Directory for state files (defaults to ~/.tele/state/)
        """
        if state_dir is None:
            state_dir = os.path.expanduser("~/.tele/state")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.chat_id = chat_id

    def _queue_path(self) -> Path:
        """Get the path to the pending queue file."""
        return self.state_dir / f"bot_{self.chat_id}_pending.jsonl"

    def append(self, msg: PendingMessage) -> None:
        """Append a message to the pending queue.

        Args:
            msg: PendingMessage to append
        """
        path = self._queue_path()
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(msg)) + '\n')

    def read_all(self) -> list[PendingMessage]:
        """Read all pending messages.

        Returns:
            List of PendingMessage objects
        """
        path = self._queue_path()
        if not path.exists():
            return []

        messages = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        messages.append(PendingMessage(**data))
                    except json.JSONDecodeError:
                        continue
        return messages

    def remove(self, message_ids: list[int]) -> None:
        """Remove messages by message_id (rewrite file without them).

        Args:
            message_ids: List of message IDs to remove
        """
        if not message_ids:
            return

        path = self._queue_path()
        if not path.exists():
            return

        # Read all, filter out removed ones
        remaining = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        if data.get('message_id') not in message_ids:
                            remaining.append(line)
                    except json.JSONDecodeError:
                        continue

        # Rewrite file with remaining messages
        with open(path, 'w', encoding='utf-8') as f:
            for line in remaining:
                f.write(line + '\n')

    def update(self, msg: PendingMessage) -> None:
        """Update a message in the queue (rewrite file).

        Args:
            msg: PendingMessage to update (matched by message_id)
        """
        path = self._queue_path()
        if not path.exists():
            return

        # Read all, update matching one
        lines = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        if data.get('message_id') == msg.message_id:
                            lines.append(json.dumps(asdict(msg)))
                        else:
                            lines.append(line)
                    except json.JSONDecodeError:
                        continue

        # Rewrite file
        with open(path, 'w', encoding='utf-8') as f:
            for line in lines:
                f.write(line + '\n')


@dataclass
class DeadLetter:
    """A message that failed processing after max retries."""
    message_id: int
    chat_id: int
    message: dict
    exec_cmd: str
    failed_at: str
    retry_count: int
    error: str


class DeadLetterQueue:
    """Manages dead-letter messages for manual retry."""

    def __init__(self, path: str):
        """Initialize dead-letter queue.

        Args:
            path: Path to the dead-letter file
        """
        self.path = Path(path)

    def append(self, dl: DeadLetter) -> None:
        """Append a dead-letter entry.

        Args:
            dl: DeadLetter to append
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(dl)) + '\n')

    def read_all(self) -> list[DeadLetter]:
        """Read all dead-letter entries.

        Returns:
            List of DeadLetter objects
        """
        if not self.path.exists():
            return []

        entries = []
        with open(self.path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        entries.append(DeadLetter(**data))
                    except json.JSONDecodeError:
                        continue
        return entries

    def remove(self, message_ids: list[int]) -> None:
        """Remove entries by message_id (rewrite file without them).

        Args:
            message_ids: List of message IDs to remove
        """
        if not message_ids:
            return

        if not self.path.exists():
            return

        # Read all, filter out removed ones
        remaining = []
        with open(self.path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        if data.get('message_id') not in message_ids:
                            remaining.append(line)
                    except json.JSONDecodeError:
                        continue

        # Rewrite file with remaining entries
        with open(self.path, 'w', encoding='utf-8') as f:
            for line in remaining:
                f.write(line + '\n')


@dataclass
class FatalError:
    """A message that encountered a fatal error (no retry value)."""
    message_id: int
    chat_id: int
    message: dict
    exec_cmd: str
    failed_at: str
    reason: str


class FatalQueue:
    """Manages fatal errors for logging/analysis."""

    def __init__(self, path: str):
        """Initialize fatal queue.

        Args:
            path: Path to the fatal errors file
        """
        self.path = Path(path)

    def append(self, fe: FatalError) -> None:
        """Append a fatal error entry.

        Args:
            fe: FatalError to append
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(fe)) + '\n')

    def read_all(self) -> list[FatalError]:
        """Read all fatal error entries.

        Returns:
            List of FatalError objects
        """
        if not self.path.exists():
            return []

        entries = []
        with open(self.path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        entries.append(FatalError(**data))
                    except json.JSONDecodeError:
                        continue
        return entries