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

    def test_init_with_endpoint_routing(self):
        """Test BotClient initialization with endpoint routing."""
        routing = {"local.server:8081": ["sendVideo"]}
        client = BotClient("test_token", api_endpoint="api.telegram.org", endpoint_routing=routing)
        assert client.endpoint_routing == routing

    def test_init_without_endpoint_routing(self):
        """Test BotClient initialization without endpoint routing."""
        client = BotClient("test_token", api_endpoint="api.telegram.org")
        assert client.endpoint_routing == {}

    @pytest.mark.asyncio
    async def test_call_api_uses_default_endpoint_when_no_routing(self):
        """Test API call uses default endpoint when method not routed."""
        client = BotClient("test_token", api_endpoint="api.telegram.org")

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": True, "result": {}})
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.return_value.__aexit__ = AsyncMock()

            await client._call_api_internal("getUpdates", {"offset": 0})

            # Check URL was constructed with default endpoint
            call_args = mock_post.call_args
            assert "api.telegram.org" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_call_api_uses_routed_endpoint(self):
        """Test API call uses routed endpoint for specified method."""
        routing = {"local.server:8081": ["sendVideo"]}
        client = BotClient("test_token", api_endpoint="api.telegram.org", endpoint_routing=routing)

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": True, "result": {}})
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.return_value.__aexit__ = AsyncMock()

            await client._call_api_internal("sendVideo", {"chat_id": 123, "video": "url"})

            # Check URL was constructed with routed endpoint
            call_args = mock_post.call_args
            assert "local.server:8081" in call_args[0][0]
            assert "api.telegram.org" not in call_args[0][0]

    @pytest.mark.asyncio
    async def test_call_api_uses_default_for_unrouted_method(self):
        """Test API call uses default endpoint when method not in routing."""
        routing = {"local.server:8081": ["sendVideo"]}
        client = BotClient("test_token", api_endpoint="api.telegram.org", endpoint_routing=routing)

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={"ok": True, "result": {}})
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.return_value.__aexit__ = AsyncMock()

            await client._call_api_internal("sendMessage", {"chat_id": 123, "text": "hi"})

            # Check URL was constructed with default endpoint (method not routed)
            call_args = mock_post.call_args
            assert "api.telegram.org" in call_args[0][0]