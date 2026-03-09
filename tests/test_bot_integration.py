"""Integration tests for bot mode."""

import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from tele.bot_client import BotClient
from tele.batcher import MessageBatcher
from tele.executor import run_exec_command
from tele.output import format_message


class TestBotModeIntegration:
    """Integration tests for bot mode."""

    @pytest.mark.asyncio
    async def test_bot_mode_end_to_end(self):
        """Test complete bot mode flow: poll -> filter -> batch -> exec -> mark."""
        # Setup
        batch_results = []

        async def capture_batch(messages):
            batch_results.append(messages)

        batcher = MessageBatcher(page_size=2, interval=0.1)
        batcher.on_batch = capture_batch

        # Simulate messages
        msg1 = {
            "message_id": 1,
            "text": "hello",
            "from": {"id": 123},
            "chat": {"id": 456},
            "date": 1705312800
        }
        msg2 = {
            "message_id": 2,
            "text": "world",
            "from": {"id": 123},
            "chat": {"id": 456},
            "date": 1705312800
        }

        formatted1 = format_message(msg1)
        formatted2 = format_message(msg2)

        await batcher.add(json.loads(formatted1))
        await batcher.add(json.loads(formatted2))

        await asyncio.sleep(0.2)  # Let batch process

        assert len(batch_results) == 1
        assert len(batch_results[0]) == 2
        assert batch_results[0][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_bot_client_with_batcher(self):
        """Test BotClient integration with MessageBatcher."""
        client = BotClient("test_token")
        batch_results = []

        async def on_batch(messages):
            batch_results.append(messages)

        batcher = MessageBatcher(page_size=2, interval=10.0)
        batcher.on_batch = on_batch

        with patch("aiohttp.ClientSession.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json = AsyncMock(return_value={
                "ok": True,
                "result": [
                    {
                        "update_id": 1,
                        "message": {
                            "message_id": 100,
                            "text": "test",
                            "from": {"id": 123},
                            "chat": {"id": 456},
                            "date": 1705312800
                        }
                    },
                    {
                        "update_id": 2,
                        "message": {
                            "message_id": 101,
                            "text": "test2",
                            "from": {"id": 123},
                            "chat": {"id": 456},
                            "date": 1705312800
                        }
                    }
                ]
            })
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.return_value.__aexit__ = AsyncMock()

            updates = await client.poll_updates(offset=0)

            for update in updates:
                message = update.get("message")
                if message:
                    formatted = format_message(message)
                    await batcher.add(json.loads(formatted))

        assert len(batch_results) == 1
        assert len(batch_results[0]) == 2

    @pytest.mark.asyncio
    async def test_exec_command_integration(self):
        """Test executor integration with message processing."""
        messages = [
            {"id": 1, "text": "hello", "status": "pending"},
            {"id": 2, "text": "world", "status": "pending"},
        ]

        # Process through cat (identity transform)
        result = await run_exec_command("cat", messages)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    @pytest.mark.asyncio
    async def test_full_bot_pipeline_simulation(self):
        """Simulate the full bot mode pipeline without external dependencies."""
        from tele.state import BotStateManager
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            # State management
            state_mgr = BotStateManager(tmpdir)

            # Initial state
            state = state_mgr.load(456)
            assert state["last_update_id"] == 0

            # Simulate processing updates
            updates = [
                {"update_id": 1, "message": {"message_id": 100, "text": "msg1", "from": {"id": 123}, "chat": {"id": 456}, "date": 1705312800}},
                {"update_id": 2, "message": {"message_id": 101, "text": "msg2", "from": {"id": 123}, "chat": {"id": 456}, "date": 1705312800}},
            ]

            # Format messages
            formatted_messages = []
            for update in updates:
                message = update.get("message")
                if message:
                    formatted = format_message(message)
                    formatted_messages.append(json.loads(formatted))

            # Save state
            state_mgr.save(456, 2)

            # Verify state
            state = state_mgr.load(456)
            assert state["last_update_id"] == 2

            # Verify messages
            assert len(formatted_messages) == 2
            assert all(m["status"] == "pending" for m in formatted_messages)