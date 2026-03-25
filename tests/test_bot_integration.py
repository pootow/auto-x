"""Integration tests for bot mode."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

import pytest

from tele.bot_client import BotClient
from tele.batcher import MessageBatcher
from tele.executor import run_exec_command
from tele.output import format_message
from tele.state import PendingQueue, PendingMessage, DeadLetterQueue, DeadLetter


def make_update(update_id: int, message_id: int, chat_id: int = 456, text: str = "test") -> dict:
    """Create a mock Telegram update."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "text": text,
            "from": {"id": 123},
            "chat": {"id": chat_id},
            "date": 1705312800
        }
    }


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

        # Simulate messages (no status in input)
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
        # Input format has no status, but has required fields
        assert "status" not in batch_results[0][0]
        assert batch_results[0][0]["id"] == 1
        assert batch_results[0][0]["chat_id"] == 456

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
            {"id": 1, "chat_id": 456, "text": "hello"},
            {"id": 2, "chat_id": 456, "text": "world"},
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
            # Input format: no status, has required fields
            assert all("status" not in m for m in formatted_messages)
            assert all("id" in m and "chat_id" in m for m in formatted_messages)


class TestPersistenceIntegration:
    """Integration tests for persistence and retry behavior."""

    @pytest.mark.asyncio
    async def test_pending_messages_replayed_on_startup(self):
        """Test that pending messages are replayed when bot restarts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(chat_id=456, state_dir=tmpdir)

            # Simulate previous session with pending messages
            msg1 = PendingMessage(
                message_id=100,
                chat_id=456,
                update_id=1,
                message={"id": 100, "chat_id": 456, "text": "pending1"},
                retry_count=0,
            )
            msg2 = PendingMessage(
                message_id=101,
                chat_id=456,
                update_id=2,
                message={"id": 101, "chat_id": 456, "text": "pending2"},
                retry_count=1,
            )
            pending_queue.append(msg1)
            pending_queue.append(msg2)

            # Simulate restart - load pending messages
            pending = pending_queue.read_all()
            assert len(pending) == 2
            assert pending[0].message_id == 100
            assert pending[0].retry_count == 0
            assert pending[1].message_id == 101
            assert pending[1].retry_count == 1

    @pytest.mark.asyncio
    async def test_successful_processing_removes_from_pending(self):
        """Test that successful processing removes messages from pending queue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(chat_id=456, state_dir=tmpdir)

            # Add messages
            for i in range(3):
                pending_queue.append(PendingMessage(
                    message_id=100 + i,
                    chat_id=456,
                    update_id=1 + i,
                    message={"id": 100 + i, "chat_id": 456, "text": f"msg{i}"},
                ))

            # Simulate successful processing of first and third
            pending_queue.remove([100, 102])

            pending = pending_queue.read_all()
            assert len(pending) == 1
            assert pending[0].message_id == 101

    @pytest.mark.asyncio
    async def test_failed_processor_moves_to_dead_letter(self):
        """Test that messages failing 3 times go to dead-letter queue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(chat_id=456, state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_456_dead.jsonl")
            dead_queue = DeadLetterQueue(dead_path)

            msg = PendingMessage(
                message_id=100,
                chat_id=456,
                update_id=1,
                message={"id": 100, "chat_id": 456, "text": "fail"},
                retry_count=3,  # Already retried 3 times
            )
            pending_queue.append(msg)

            # Simulate max retries exceeded - move to dead letter
            dl = DeadLetter(
                message_id=msg.message_id,
                chat_id=msg.chat_id,
                message=msg.message,
                exec_cmd="processor",
                failed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                retry_count=msg.retry_count,
                error="Max retries exceeded",
            )
            dead_queue.append(dl)
            pending_queue.remove([msg.message_id])

            # Verify
            assert len(pending_queue.read_all()) == 0
            dead = dead_queue.read_all()
            assert len(dead) == 1
            assert dead[0].message_id == 100
            assert dead[0].retry_count == 3

    @pytest.mark.asyncio
    async def test_retry_dead_removes_successful(self):
        """Test that --retry-dead removes successful retries from dead-letter file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dead_path = str(Path(tmpdir) / "bot_456_dead.jsonl")
            dead_queue = DeadLetterQueue(dead_path)

            # Add multiple dead letters
            for i in range(3):
                dead_queue.append(DeadLetter(
                    message_id=100 + i,
                    chat_id=456,
                    message={"id": 100 + i, "chat_id": 456, "text": f"msg{i}"},
                    exec_cmd="processor",
                    failed_at="2024-01-15T10:00:00Z",
                    retry_count=3,
                    error="Error",
                ))

            # Simulate successful retry of first and third
            dead_queue.remove([100, 102])

            dead = dead_queue.read_all()
            assert len(dead) == 1
            assert dead[0].message_id == 101

    @pytest.mark.asyncio
    async def test_full_persistence_flow_with_mocked_processor(self):
        """Test the full persistence flow: receive -> pending -> process -> remove."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(chat_id=456, state_dir=tmpdir)
            batch_results = []

            async def mock_processor(messages):
                """Simulate a processor that returns success for all messages."""
                for msg in messages:
                    batch_results.append(msg)
                return [{"id": m["id"], "chat_id": m["chat_id"], "status": "success"} for m in messages]

            batcher = MessageBatcher(page_size=2, interval=0.1)

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await mock_processor(messages)
                # Simulate successful processing - remove from pending
                success_ids = [r["id"] for r in results if r["status"] == "success"]
                pending_queue.remove(success_ids)

            batcher.on_batch = process_batch

            # Simulate receiving updates
            for i in range(2):
                msg = PendingMessage(
                    message_id=100 + i,
                    chat_id=456,
                    update_id=1 + i,
                    message={"id": 100 + i, "chat_id": 456, "text": f"msg{i}"},
                )
                pending_queue.append(msg)
                await batcher.add({
                    "message_id": msg.message_id,
                    "chat_id": msg.chat_id,
                    "update_id": msg.update_id,
                    "message": msg.message,
                })

            await asyncio.sleep(0.2)  # Let batch process

            # Verify all processed
            assert len(batch_results) == 2
            # Verify pending queue is empty
            assert len(pending_queue.read_all()) == 0

    @pytest.mark.asyncio
    async def test_processor_crash_triggers_retry(self):
        """Test that processor crash schedules a retry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(chat_id=456, state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_456_dead.jsonl")
            dead_queue = DeadLetterQueue(dead_path)

            call_count = 0

            async def flaky_processor(messages):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    # Simulate crash
                    raise RuntimeError("Processor crashed")
                # Success on third try
                return [{"id": m["id"], "chat_id": m["chat_id"], "status": "success"} for m in messages]

            batcher = MessageBatcher(page_size=1, interval=0.1)
            retry_count = 0
            MAX_RETRIES = 3

            async def process_batch(items):
                nonlocal retry_count
                messages = [item["message"] for item in items]
                try:
                    results = await flaky_processor(messages)
                    pending_queue.remove([r["id"] for r in results])
                except RuntimeError:
                    # Simulate retry logic
                    retry_count += 1
                    if retry_count >= MAX_RETRIES:
                        # Move to dead letter
                        for item in items:
                            dead_queue.append(DeadLetter(
                                message_id=item["message_id"],
                                chat_id=item["chat_id"],
                                message=item["message"],
                                exec_cmd="processor",
                                failed_at=datetime.now(timezone.utc).isoformat(),
                                retry_count=retry_count,
                                error="Max retries",
                            ))
                            pending_queue.remove([item["message_id"]])

            batcher.on_batch = process_batch

            msg = PendingMessage(
                message_id=100,
                chat_id=456,
                update_id=1,
                message={"id": 100, "chat_id": 456, "text": "test"},
            )
            pending_queue.append(msg)
            await batcher.add({
                "message_id": msg.message_id,
                "chat_id": msg.chat_id,
                "update_id": msg.update_id,
                "message": msg.message,
            })

            await asyncio.sleep(0.2)

            # First attempt should have crashed
            assert call_count == 1
            assert retry_count == 1
            # Message should still be in pending (retry scheduled)
            assert len(pending_queue.read_all()) == 1

    @pytest.mark.asyncio
    async def test_non_retriable_failure_marked_but_not_retried(self):
        """Test that processor returning status=failed is not retried."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(chat_id=456, state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_456_dead.jsonl")
            dead_queue = DeadLetterQueue(dead_path)

            async def failing_processor(messages):
                # Processor explicitly returns failed (non-retriable)
                return [{"id": m["id"], "chat_id": m["chat_id"], "status": "failed"} for m in messages]

            batcher = MessageBatcher(page_size=1, interval=0.1)

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await failing_processor(messages)
                # Both success and non-retriable failed should be removed from pending
                to_remove = [r["id"] for r in results]
                pending_queue.remove(to_remove)
                # Non-retriable failures don't go to dead-letter either

            batcher.on_batch = process_batch

            msg = PendingMessage(
                message_id=100,
                chat_id=456,
                update_id=1,
                message={"id": 100, "chat_id": 456, "text": "test"},
            )
            pending_queue.append(msg)
            await batcher.add({
                "message_id": msg.message_id,
                "chat_id": msg.chat_id,
                "update_id": msg.update_id,
                "message": msg.message,
            })

            await asyncio.sleep(0.2)

            # Message should be removed from pending (not scheduled for retry)
            assert len(pending_queue.read_all()) == 0
            # Message should NOT be in dead-letter (non-retriable failure)
            assert len(dead_queue.read_all()) == 0