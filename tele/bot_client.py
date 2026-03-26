"""Bot API client for Telegram operations."""

import asyncio
import logging
import aiohttp
from typing import Optional, List, Dict, Any

from .retry import retry_async

logger = logging.getLogger(__name__)


class BotClient:
    """Bot API client using HTTP long polling."""

    API_BASE = "https://{api_endpoint}/bot{token}/{method}"

    def __init__(self, token: str, api_endpoint: str = "api.telegram.org", timeout: int = 30):
        """Initialize Bot API client.

        Args:
            token: Bot token from @BotFather
            api_endpoint: API endpoint URL (default: "api.telegram.org")
            timeout: Long polling timeout in seconds
        """
        self.token = token
        self.api_endpoint = api_endpoint
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

    async def _reset_session(self) -> None:
        """Reset HTTP session (used after persistent failures)."""
        await self.close()
        logger.debug("HTTP session reset")

    async def _call_api_internal(self, method: str, params: dict = None) -> dict:
        """Internal API call without retry (used by retry wrapper).

        Args:
            method: API method name
            params: Method parameters

        Returns:
            API response data

        Raises:
            aiohttp.ClientError: Network/HTTP errors
            RuntimeError: If API returns error response
        """
        session = await self._get_session()
        url = self.API_BASE.format(api_endpoint=self.api_endpoint, token=self.token, method=method)
        logger.debug("Calling API method: %s with params: %s", method, params)

        async with session.post(url, json=params or {}) as response:
            # Parse response body first to capture Telegram's error description
            data = await response.json()
            if not data.get("ok"):
                error_desc = data.get('description', 'Unknown error')
                error_code = data.get('error_code', response.status)
                logger.error("API error %s: %s", error_code, error_desc)
                raise RuntimeError(f"API error: {error_desc}")
            logger.debug("API call successful: %s", method)
            return data.get("result", {})

    async def _call_api(self, method: str, params: dict = None) -> dict:
        """Call Bot API method with automatic retry on transient failures.

        Args:
            method: API method name
            params: Method parameters

        Returns:
            API response data

        Raises:
            RuntimeError: If API call fails after all retries
        """
        try:
            return await retry_async(
                self._call_api_internal,
                method,
                params,
                retry_exceptions=(aiohttp.ClientError, asyncio.TimeoutError),
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Reset session on persistent failures
            logger.warning("API call failed after retries, resetting session: %s", e)
            await self._reset_session()
            raise RuntimeError(f"API call failed: {e}") from e

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

    async def send_video(
        self,
        chat_id: int,
        video: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None
    ) -> dict:
        """Send a video by URL.

        Args:
            chat_id: Target chat ID
            video: Video URL or file_id
            caption: Optional caption
            reply_to_message_id: Optional message ID to reply to

        Returns:
            Sent message object
        """
        params = {
            "chat_id": chat_id,
            "video": video,
            "parse_mode": "MarkdownV2",
        }
        if caption:
            params["caption"] = caption
        if reply_to_message_id:
            params["reply_to_message_id"] = reply_to_message_id

        logger.debug("Sending video to chat %s", chat_id)
        return await self._call_api("sendVideo", params)

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None
    ) -> dict:
        """Send a photo by URL.

        Args:
            chat_id: Target chat ID
            photo: Photo URL or file_id
            caption: Optional caption
            reply_to_message_id: Optional message ID to reply to

        Returns:
            Sent message object
        """
        params = {
            "chat_id": chat_id,
            "photo": photo,
            "parse_mode": "MarkdownV2",
        }
        if caption:
            params["caption"] = caption
        if reply_to_message_id:
            params["reply_to_message_id"] = reply_to_message_id

        logger.debug("Sending photo to chat %s", chat_id)
        return await self._call_api("sendPhoto", params)