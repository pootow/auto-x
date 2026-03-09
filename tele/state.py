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