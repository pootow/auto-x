"""State management for incremental message processing."""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_write_json(path: Path, data: dict, description: str = "state") -> bool:
    """Write JSON to file atomically.

    Args:
        path: Path to write to
        data: Data to write
        description: Description for error messages

    Returns:
        True on success, False on failure (never raises)
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        temp_path.replace(path)
        return True
    except Exception as e:
        logger.error("Failed to write %s to %s: %s", description, path, e)
        return False


def safe_read_json(path: Path, default=None):
    """Read JSON from file safely.

    Args:
        path: Path to read from
        default: Default value if file doesn't exist or on error

    Returns:
        Parsed JSON data or default value (never raises)
    """
    if not path.exists():
        return default

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to read %s: %s", path, e)
        return default


def safe_write_line(path: Path, line: str) -> bool:
    """Append a line to a file safely.

    Args:
        path: Path to write to
        line: Line to append (without newline)

    Returns:
        True on success, False on failure (never raises)
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        return True
    except Exception as e:
        logger.error("Failed to append to %s: %s", path, e)
        return False


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
    """Manages bot mode state (offset-based).

    Bot API offset is global (not per-chat), so state is stored in a single file.
    """

    def __init__(self, state_dir: Optional[str] = None):
        """Initialize bot state manager.

        Args:
            state_dir: Directory for state files (defaults to ~/.tele/state/)
        """
        if state_dir is None:
            state_dir = os.path.expanduser("~/.tele/state")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self) -> Path:
        """Get the path to the bot state file.

        Returns:
            Path to state file (bot.json)
        """
        return self.state_dir / "bot.json"

    def load(self) -> dict:
        """Load bot state.

        Returns:
            dict with last_update_id (0 if no state) and last_processed_at
        """
        path = self._state_path()
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # Ensure required fields exist (backward compatibility)
                if 'last_update_id' not in data:
                    data['last_update_id'] = 0
                if 'last_processed_at' not in data:
                    data['last_processed_at'] = None
                return data
            except (json.JSONDecodeError, KeyError):
                pass
        return {"last_update_id": 0, "last_processed_at": None}

    def save(self, update_id: int) -> None:
        """Save bot state after successful processing.

        Args:
            update_id: Last processed update ID
        """
        path = self._state_path()
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
    ready_at: Optional[str] = None  # ISO timestamp, None = ready immediately
    created_at: Optional[str] = None  # ISO timestamp when message was queued


class PendingQueue:
    """Manages pending messages for crash recovery.

    Bot API offset is global (not per-chat), so pending messages are stored
    in a single queue file. Each message carries its own chat_id for
    operations (reactions, replies).

    All I/O operations are safe - they never raise exceptions.
    On failure, they log errors and return appropriate default values.
    """

    def __init__(self, state_dir: Optional[str] = None):
        """Initialize pending queue.

        Args:
            state_dir: Directory for state files (defaults to ~/.tele/state/)
        """
        if state_dir is None:
            state_dir = os.path.expanduser("~/.tele/state")
        self.state_dir = Path(state_dir)
        # In-memory cache for resilience
        self._cache: Optional[list[PendingMessage]] = None

    def _queue_path(self) -> Path:
        """Get the path to the pending queue file."""
        return self.state_dir / "bot_pending.jsonl"

    def append(self, msg: PendingMessage) -> bool:
        """Append a message to the pending queue.

        Automatically populates created_at if not set.

        Args:
            msg: PendingMessage to append

        Returns:
            True on success, False on failure (never raises)
        """
        # Auto-populate created_at if not set
        if msg.created_at is None:
            msg.created_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self._queue_path()
        success = safe_write_line(path, json.dumps(asdict(msg)))
        if success:
            # Invalidate cache
            self._cache = None
        return success

    def read_all(self) -> list[PendingMessage]:
        """Read all pending messages.

        Returns:
            List of PendingMessage objects (empty list on error, never raises)
        """
        if self._cache is not None:
            return self._cache.copy()

        path = self._queue_path()
        if not path.exists():
            self._cache = []
            return []

        messages = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            messages.append(PendingMessage(**data))
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning("Skipping invalid line in %s: %s", path, e)
                            continue
        except Exception as e:
            logger.error("Failed to read %s: %s", path, e)

        self._cache = messages
        return messages.copy()

    def read_ready(self) -> list[PendingMessage]:
        """Read messages that are ready for processing.

        A message is ready if:
        - ready_at is None (new message, ready immediately)
        - ready_at <= now (retry backoff has passed)

        Returns:
            List of ready PendingMessage objects
        """
        messages = self.read_all()
        now = datetime.now(timezone.utc)

        ready = []
        for msg in messages:
            if msg.ready_at is None:
                ready.append(msg)
            else:
                try:
                    ready_time = datetime.fromisoformat(
                        msg.ready_at.replace('Z', '+00:00')
                    )
                    if ready_time <= now:
                        ready.append(msg)
                except (ValueError, TypeError):
                    # Invalid timestamp, treat as ready
                    ready.append(msg)

        return ready

    def remove(self, message_ids: list[int]) -> bool:
        """Remove messages by message_id only (DEPRECATED - use remove_by_chat).

        WARNING: This method does not consider chat_id and may incorrectly
        remove messages from different chats that happen to have the same
        message_id. Telegram message_ids are per-chat sequences.

        Args:
            message_ids: List of message IDs to remove

        Returns:
            True on success, False on failure (never raises)
        """
        if not message_ids:
            return True

        path = self._queue_path()
        if not path.exists():
            return True

        try:
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

            # Atomic rewrite: write to temp file, then rename
            temp_path = path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in remaining:
                    f.write(line + '\n')

            temp_path.replace(path)
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to remove from %s: %s", path, e)
            return False

    def remove_by_chat(self, ids: list[tuple[int, int]]) -> bool:
        """Remove messages by (message_id, chat_id) tuple.

        Telegram message_ids are per-chat sequences. Chat A's message_id=100
        and Chat B's message_id=100 are DIFFERENT messages. This method
        ensures only the correct message from the correct chat is removed.

        Args:
            ids: List of (message_id, chat_id) tuples to remove

        Returns:
            True on success, False on failure (never raises)
        """
        if not ids:
            return True

        path = self._queue_path()
        if not path.exists():
            return True

        try:
            # Convert to set for O(1) lookup
            remove_set = set(ids)

            # Read all, filter out removed ones
            remaining = []
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            key = (data.get('message_id'), data.get('chat_id'))
                            if key not in remove_set:
                                remaining.append(line)
                        except json.JSONDecodeError:
                            continue

            # Atomic rewrite: write to temp file, then rename
            temp_path = path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in remaining:
                    f.write(line + '\n')

            temp_path.replace(path)
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to remove from %s: %s", path, e)
            return False

    def update(self, msg: PendingMessage) -> bool:
        """Update a message in the queue (rewrite file).

        Args:
            msg: PendingMessage to update (matched by message_id)

        Returns:
            True on success, False on failure (never raises)
        """
        path = self._queue_path()
        if not path.exists():
            return False

        try:
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

            # Atomic rewrite
            temp_path = path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')

            temp_path.replace(path)
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to update %s: %s", path, e)
            return False

    def schedule_retry(
        self,
        message_id: int,
        chat_id: int,
        backoff_seconds: float,
    ) -> bool:
        """Schedule a message for retry with backoff.

        Updates retry_count and sets ready_at to now + backoff_seconds.

        Args:
            message_id: Message ID to retry
            chat_id: Chat ID (for cross-chat safety)
            backoff_seconds: Seconds to wait before retry

        Returns:
            True on success, False if message not found
        """
        messages = self.read_all()
        for msg in messages:
            if msg.message_id == message_id and msg.chat_id == chat_id:
                msg.retry_count += 1
                msg.ready_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
                ).isoformat().replace('+00:00', 'Z')
                return self.update_by_chat(msg)

        return False

    def update_by_chat(self, msg: PendingMessage) -> bool:
        """Update a message in the queue by (message_id, chat_id).

        This is the correct method to use - it prevents cross-chat collision.

        Args:
            msg: PendingMessage to update

        Returns:
            True on success, False on failure
        """
        if not self._queue_path().exists():
            return False

        try:
            lines = []
            with open(self._queue_path(), 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            if (data.get('message_id') == msg.message_id and
                                data.get('chat_id') == msg.chat_id):
                                lines.append(json.dumps(asdict(msg)))
                            else:
                                lines.append(line)
                        except json.JSONDecodeError:
                            continue

            temp_path = self._queue_path().with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')

            temp_path.replace(self._queue_path())
            self._cache = None
            return True
        except Exception as e:
            logger.error("Failed to update %s: %s", self._queue_path(), e)
            return False


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
    """Manages dead-letter messages for manual retry.

    All I/O operations are safe - they never raise exceptions.
    On failure, they log errors and return appropriate default values.
    """

    def __init__(self, path: str):
        """Initialize dead-letter queue.

        Args:
            path: Path to the dead-letter file
        """
        self.path = Path(path)

    def append(self, dl: DeadLetter) -> bool:
        """Append a dead-letter entry.

        Args:
            dl: DeadLetter to append

        Returns:
            True on success, False on failure (never raises)
        """
        return safe_write_line(self.path, json.dumps(asdict(dl)))

    def read_all(self) -> list[DeadLetter]:
        """Read all dead-letter entries.

        Returns:
            List of DeadLetter objects (empty list on error, never raises)
        """
        if not self.path.exists():
            return []

        entries = []
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            entries.append(DeadLetter(**data))
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning("Skipping invalid line in %s: %s", self.path, e)
                            continue
        except Exception as e:
            logger.error("Failed to read %s: %s", self.path, e)

        return entries

    def remove(self, message_ids: list[int]) -> bool:
        """Remove entries by message_id (rewrite file without them).

        Args:
            message_ids: List of message IDs to remove

        Returns:
            True on success, False on failure (never raises)
        """
        if not message_ids:
            return True

        if not self.path.exists():
            return True

        try:
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

            # Atomic rewrite
            temp_path = self.path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                for line in remaining:
                    f.write(line + '\n')

            temp_path.replace(self.path)
            return True
        except Exception as e:
            logger.error("Failed to remove from %s: %s", self.path, e)
            return False


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
    """Manages fatal errors for logging/analysis.

    All I/O operations are safe - they never raise exceptions.
    On failure, they log errors and return appropriate default values.
    """

    def __init__(self, path: str):
        """Initialize fatal queue.

        Args:
            path: Path to the fatal errors file
        """
        self.path = Path(path)

    def append(self, fe: FatalError) -> bool:
        """Append a fatal error entry.

        Args:
            fe: FatalError to append

        Returns:
            True on success, False on failure (never raises)
        """
        return safe_write_line(self.path, json.dumps(asdict(fe)))

    def read_all(self) -> list[FatalError]:
        """Read all fatal error entries.

        Returns:
            List of FatalError objects (empty list on error, never raises)
        """
        if not self.path.exists():
            return []

        entries = []
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            entries.append(FatalError(**data))
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning("Skipping invalid line in %s: %s", self.path, e)
                            continue
        except Exception as e:
            logger.error("Failed to read %s: %s", self.path, e)

        return entries