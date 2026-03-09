"""Tests for Bot API client."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from tele.bot_client import BotClient


class TestBotClient:
    """Test cases for BotClient."""

    def test_init(self):
        """Test BotClient initialization."""
        client = BotClient("test_token")
        assert client.token == "test_token"
        assert client.timeout == 30

    def test_init_with_custom_timeout(self):
        """Test BotClient with custom timeout."""
        client = BotClient("test_token", timeout=60)
        assert client.timeout == 60

    @pytest.mark.asyncio
    async def test_poll_updates_returns_messages(self):
        """BotClient.poll_updates should return list of updates."""
        client = BotClient("test_token")

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={
                "ok": True,
                "result": [
                    {"update_id": 1, "message": {"message_id": 100, "text": "hello"}}
                ]
            })
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.return_value.__aexit__ = AsyncMock()

            updates = await client.poll_updates(offset=0)
            assert len(updates) == 1
            assert updates[0]["update_id"] == 1

    @pytest.mark.asyncio
    async def test_add_reaction_success(self):
        """BotClient.add_reaction should call setMessageReaction API."""
        client = BotClient("test_token")

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": True, "result": True})
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.return_value.__aexit__ = AsyncMock()

            result = await client.add_reaction(chat_id=123, message_id=456, emoji="✅")
            assert result is True

    @pytest.mark.asyncio
    async def test_close_session(self):
        """BotClient.close should close the HTTP session."""
        client = BotClient("test_token")
        # Create session
        session = await client._get_session()
        assert session is not None

        await client.close()
        assert client._session is None or client._session.closed