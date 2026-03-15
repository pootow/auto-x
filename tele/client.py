"""Telethon client wrapper for Telegram API operations."""

import logging
import os
from typing import Optional, Union, List, AsyncIterator

from telethon import TelegramClient
from telethon.tl.types import InputPeerUser, InputPeerChat, InputPeerChannel, PeerUser, PeerChat, PeerChannel
from telethon.tl.functions.messages import SearchRequest
from telethon.tl.types import InputMessagesFilterEmpty

logger = logging.getLogger(__name__)


class TeleClient:
    """Wrapper around Telethon client with convenience methods."""

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        session_name: Optional[str] = None,
        session_dir: Optional[str] = None,
    ):
        """Initialize the Telegram client.

        Args:
            api_id: Telegram API ID (defaults to TELEGRAM_API_ID env var)
            api_hash: Telegram API hash (defaults to TELEGRAM_API_HASH env var)
            session_name: Session name (defaults to "tele_tool")
            session_dir: Directory for session files (defaults to ~/.tele/)
        """
        self.api_id = api_id or int(os.environ["TELEGRAM_API_ID"])
        self.api_hash = api_hash or os.environ["TELEGRAM_API_HASH"]
        self.session_name = session_name or "tele_tool"

        if session_dir is None:
            session_dir = os.path.expanduser("~/.tele")
        os.makedirs(session_dir, exist_ok=True)

        session_path = os.path.join(session_dir, self.session_name)
        self.client = TelegramClient(session_path, self.api_id, self.api_hash)

    async def connect(self) -> None:
        """Connect to Telegram."""
        logger.debug("Connecting to Telegram...")
        await self.client.connect()
        logger.info("Connected to Telegram")

    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        logger.debug("Disconnecting from Telegram...")
        await self.client.disconnect()
        logger.info("Disconnected from Telegram")

    async def ensure_authorized(self) -> None:
        """Ensure the client is authorized, prompting for login if needed."""
        if not await self.client.is_user_authorized():
            logger.info("Not authorized, requesting login...")
            await self.client.send_code_request(self.api_id)
            print("Enter the code you received: ")
            code = input()
            await self.client.sign_in(self.api_id, code)
            logger.info("Successfully authorized")

    async def resolve_chat(self, chat: Union[str, int]) -> Union[InputPeerUser, InputPeerChat, InputPeerChannel]:
        """Resolve a chat name or ID to an input peer.

        Args:
            chat: Chat name, username, or ID

        Returns:
            InputPeer suitable for API calls
        """
        logger.debug("Resolving chat: %s", chat)
        # If it's already an integer, treat as ID
        if isinstance(chat, int):
            try:
                entity = await self.client.get_entity(chat)
                result = self.client.get_input_entity(entity)
                logger.debug("Resolved chat ID %s to %s", chat, type(result).__name__)
                return result
            except Exception:
                raise ValueError(f"Could not find chat with ID: {chat}")

        # Try to resolve by username (with or without @)
        chat_str = str(chat)
        if chat_str.startswith("@"):
            chat_str = chat_str[1:]

        # Try username lookup
        try:
            entity = await self.client.get_entity(chat_str)
            result = self.client.get_input_entity(entity)
            logger.debug("Resolved username '%s' to %s", chat_str, type(result).__name__)
            return result
        except Exception:
            pass

        # Try searching in dialogs
        async for dialog in self.client.iter_dialogs():
            if dialog.name == chat or dialog.name.lower() == chat_str.lower():
                result = self.client.get_input_entity(dialog.entity)
                logger.debug("Resolved dialog name '%s' to %s", chat, type(result).__name__)
                return result

        raise ValueError(f"Could not resolve chat: {chat}")

    async def get_chat_id(self, chat: Union[str, int]) -> int:
        """Get the numeric ID for a chat.

        Args:
            chat: Chat name, username, or ID

        Returns:
            Numeric chat ID
        """
        peer = await self.resolve_chat(chat)
        if isinstance(peer, InputPeerUser):
            return peer.user_id
        elif isinstance(peer, InputPeerChat):
            return -peer.chat_id  # Chats have negative IDs
        elif isinstance(peer, InputPeerChannel):
            return -1000000000000 - peer.channel_id  # Channels have special negative IDs
        else:
            raise ValueError(f"Unknown peer type: {type(peer)}")

    async def get_messages(
        self,
        chat: Union[str, int],
        min_id: Optional[int] = None,
        max_id: Optional[int] = None,
        limit: Optional[int] = None,
        reverse: bool = False,
    ) -> List:
        """Get messages from a chat.

        Args:
            chat: Chat name, username, or ID
            min_id: Minimum message ID (exclusive)
            max_id: Maximum message ID (exclusive)
            limit: Maximum number of messages to fetch
            reverse: If True, fetch in ascending order (oldest first)

        Returns:
            List of Message objects
        """
        peer = await self.resolve_chat(chat)
        messages = await self.client.get_messages(
            peer,
            min_id=min_id,
            max_id=max_id,
            limit=limit,
            reverse=reverse,
        )
        return messages if isinstance(messages, list) else [messages]

    async def iter_messages(
        self,
        chat: Union[str, int],
        min_id: Optional[int] = None,
        max_id: Optional[int] = None,
        limit: Optional[int] = None,
        reverse: bool = False,
    ) -> AsyncIterator:
        """Iterate over messages from a chat.

        Args:
            chat: Chat name, username, or ID
            min_id: Minimum message ID (exclusive)
            max_id: Maximum message ID (exclusive)
            limit: Maximum number of messages to fetch
            reverse: If True, fetch in ascending order (oldest first)

        Yields:
            Message objects
        """
        peer = await self.resolve_chat(chat)
        async for message in self.client.iter_messages(
            peer,
            min_id=min_id,
            max_id=max_id,
            limit=limit,
            reverse=reverse,
        ):
            yield message

    async def search_messages(
        self,
        chat: Union[str, int],
        query: str,
        limit: Optional[int] = None,
    ) -> List:
        """Search for messages in a chat.

        Args:
            chat: Chat name, username, or ID
            query: Search query
            limit: Maximum number of messages to fetch

        Returns:
            List of matching Message objects
        """
        peer = await self.resolve_chat(chat)
        messages = await self.client.get_messages(
            peer,
            search=query,
            limit=limit,
        )
        return messages if isinstance(messages, list) else [messages]

    async def iter_search_messages(
        self,
        chat: Union[str, int],
        query: str,
        limit: Optional[int] = None,
    ) -> AsyncIterator:
        """Iterate over search results in a chat.

        Args:
            chat: Chat name, username, or ID
            query: Search query
            limit: Maximum number of messages to fetch

        Yields:
            Message objects
        """
        peer = await self.resolve_chat(chat)
        async for message in self.client.iter_messages(
            peer,
            search=query,
            limit=limit,
        ):
            yield message

    async def add_reaction(
        self,
        chat: Union[str, int],
        message_id: int,
        emoji: str = "✅",
    ) -> bool:
        """Add a reaction to a message.

        Args:
            chat: Chat name, username, or ID
            message_id: ID of the message
            emoji: Emoji to react with

        Returns:
            True if successful
        """
        peer = await self.resolve_chat(chat)
        await self.client.send_reaction(peer, message_id, emoji)
        logger.debug("Added reaction %s to message %s", emoji, message_id)
        return True

    async def get_dialogs(self) -> List:
        """Get all dialogs (chats).

        Returns:
            List of Dialog objects
        """
        dialogs = await self.client.get_dialogs()
        return dialogs if isinstance(dialogs, list) else [dialogs]