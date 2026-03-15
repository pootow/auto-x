"""Bot API client for Telegram operations."""

import logging
import aiohttp
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class BotClient:
    """Bot API client using HTTP long polling."""

    API_BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, timeout: int = 30):
        """Initialize Bot API client.

        Args:
            token: Bot token from @BotFather
            timeout: Long polling timeout in seconds
        """
        self.token = token
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            logger.debug("Creating new HTTP session")
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            logger.debug("Closing HTTP session")
            await self._session.close()

    async def _call_api(self, method: str, params: dict = None) -> dict:
        """Call Bot API method.

        Args:
            method: API method name
            params: Method parameters

        Returns:
            API response data

        Raises:
            RuntimeError: If API call fails
        """
        session = await self._get_session()
        url = self.API_BASE.format(token=self.token, method=method)
        logger.debug("Calling API method: %s with params: %s", method, params)

        async with session.post(url, json=params or {}) as response:
            response.raise_for_status()
            data = await response.json()
            if not data.get("ok"):
                logger.error("API error: %s", data.get('description'))
                raise RuntimeError(f"API error: {data.get('description')}")
            logger.debug("API call successful: %s", method)
            return data.get("result", {})

    async def poll_updates(self, offset: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """Poll for new updates using long polling.

        Args:
            offset: Start from this update_id
            limit: Max updates to fetch

        Returns:
            List of update objects
        """
        params = {
            "offset": offset,
            "limit": limit,
            "timeout": self.timeout,
            "allowed_updates": ["message", "channel_post"]
        }
        updates = await self._call_api("getUpdates", params)
        if updates:
            logger.debug("Received %s updates", len(updates))
        return updates

    async def add_reaction(
        self,
        chat_id: int,
        message_id: int,
        emoji: str = "✅"
    ) -> bool:
        """Add reaction to a message.

        Args:
            chat_id: Target chat ID
            message_id: Message ID
            emoji: Reaction emoji

        Returns:
            True if successful
        """
        logger.debug("Adding reaction %s to message %s in chat %s", emoji, message_id, chat_id)
        await self._call_api("setMessageReaction", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}]
        })
        return True