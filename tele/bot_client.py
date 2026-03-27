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

        This method NEVER raises exceptions - it returns an empty dict on failure.
        This ensures the daemon never crashes due to API failures.

        Args:
            method: API method name
            params: Method parameters

        Returns:
            API response data, or {} on failure (never raises)
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
            return {}
        except RuntimeError as e:
            # API error response
            logger.error("API error: %s", e)
            return {}
        except Exception as e:
            # Unexpected error - log and return empty
            logger.error("Unexpected API error: %s", e, exc_info=True)
            return {}

    async def poll_updates(self, offset: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """Poll for new updates using long polling.

        This method NEVER raises exceptions - it returns an empty list on failure.
        This ensures the daemon never crashes due to polling failures.

        Args:
            offset: Start from this update_id
            limit: Max updates to fetch

        Returns:
            List of update objects, or [] on failure (never raises)
        """
        params = {
            "offset": offset,
            "limit": limit,
            "timeout": self.timeout,
            "allowed_updates": ["message", "channel_post"]
        }
        try:
            updates = await self._call_api("getUpdates", params)
            if updates and isinstance(updates, list):
                logger.debug("Received %s updates", len(updates))
                return updates
            return []
        except Exception as e:
            # Should not happen since _call_api never raises, but be safe
            logger.error("Unexpected error in poll_updates: %s", e)
            return []

    async def add_reaction(
        self,
        chat_id: int,
        message_id: int,
        emoji: str = "✅"
    ) -> bool:
        """Add reaction to a message.

        This method NEVER raises exceptions - it returns False on failure.
        This ensures the daemon never crashes due to reaction failures.

        Args:
            chat_id: Target chat ID
            message_id: Message ID
            emoji: Reaction emoji

        Returns:
            True if successful, False on failure (never raises)
        """
        logger.debug("Adding reaction %s to message %s in chat %s", emoji, message_id, chat_id)
        result = await self._call_api("setMessageReaction", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}]
        })
        return bool(result)

    async def send_video(
        self,
        chat_id: int,
        video: str,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        cover: Optional[str] = None,
        duration: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> dict:
        """Send a video by URL.

        This method NEVER raises exceptions - it returns an empty dict on failure.
        This ensures the daemon never crashes due to video send failures.

        Args:
            chat_id: Target chat ID
            video: Video URL or file_id
            caption: Optional caption
            reply_to_message_id: Optional message ID to reply to
            cover: Optional thumbnail URL
            duration: Optional video duration in seconds
            width: Optional video width
            height: Optional video height

        Returns:
            Sent message object, or {} on failure (never raises)
        """
        params = {
            "chat_id": chat_id,
            "video": video,
            "parse_mode": "HTML",
            "supports_streaming": True,
        }
        if caption:
            params["caption"] = caption
        if reply_to_message_id:
            params["reply_to_message_id"] = reply_to_message_id
        if cover:
            params["thumbnail"] = cover
        if duration:
            params["duration"] = duration
        if width:
            params["width"] = width
        if height:
            params["height"] = height

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

        This method NEVER raises exceptions - it returns an empty dict on failure.
        This ensures the daemon never crashes due to photo send failures.

        Args:
            chat_id: Target chat ID
            photo: Photo URL or file_id
            caption: Optional caption
            reply_to_message_id: Optional message ID to reply to

        Returns:
            Sent message object, or {} on failure (never raises)
        """
        params = {
            "chat_id": chat_id,
            "photo": photo,
            "parse_mode": "HTML",
        }
        if caption:
            params["caption"] = caption
        if reply_to_message_id:
            params["reply_to_message_id"] = reply_to_message_id

        logger.debug("Sending photo to chat %s", chat_id)
        return await self._call_api("sendPhoto", params)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
        parse_mode: str = "HTML"
    ) -> dict:
        """Send a text message.

        This method NEVER raises exceptions - it returns an empty dict on failure.
        This ensures the daemon never crashes due to message send failures.

        Args:
            chat_id: Target chat ID
            text: Message text
            reply_to_message_id: Optional message ID to reply to
            parse_mode: Parse mode for text formatting

        Returns:
            Sent message object, or {} on failure (never raises)
        """
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_to_message_id:
            params["reply_to_message_id"] = reply_to_message_id

        logger.debug("Sending message to chat %s", chat_id)
        return await self._call_api("sendMessage", params)