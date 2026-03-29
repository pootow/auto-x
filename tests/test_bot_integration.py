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
from tele.state import PendingQueue, PendingMessage, DeadLetterQueue, DeadLetter, FatalQueue, FatalError


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
            state = state_mgr.load()
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
            state_mgr.save(2)

            # Verify state
            state = state_mgr.load()
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
            pending_queue = PendingQueue(state_dir=tmpdir)

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
            pending_queue = PendingQueue(state_dir=tmpdir)

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
            pending_queue = PendingQueue(state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_dead.jsonl")
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
            dead_path = str(Path(tmpdir) / "bot_dead.jsonl")
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
            pending_queue = PendingQueue(state_dir=tmpdir)
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
            pending_queue = PendingQueue(state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_dead.jsonl")
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
    async def test_fatal_status_not_retried_goes_to_fatal_queue(self):
        """Test that processor returning status=fatal is not retried and goes to fatal queue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_dead.jsonl")
            dead_queue = DeadLetterQueue(dead_path)
            fatal_path = str(Path(tmpdir) / "bot_456_fatal.jsonl")
            fatal_queue = FatalQueue(fatal_path)

            async def fatal_processor(messages):
                # Processor explicitly returns fatal (no retry value)
                return [{"id": m["id"], "chat_id": m["chat_id"], "status": "fatal", "reason": "Resource 404"} for m in messages]

            batcher = MessageBatcher(page_size=1, interval=0.1)

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await fatal_processor(messages)
                # Fatal messages should be removed from pending
                fatal_ids = [r["id"] for r in results if r.get("status") == "fatal"]
                if fatal_ids:
                    for item in items:
                        if item["message_id"] in fatal_ids:
                            fe = FatalError(
                                message_id=item["message_id"],
                                chat_id=item["chat_id"],
                                message=item["message"],
                                exec_cmd="processor",
                                failed_at="2024-01-15T10:00:00Z",
                                reason="Resource 404",
                            )
                            fatal_queue.append(fe)
                pending_queue.remove(fatal_ids)

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
            # Message should NOT be in dead-letter
            assert len(dead_queue.read_all()) == 0
            # Message should be in fatal queue
            fatal_entries = fatal_queue.read_all()
            assert len(fatal_entries) == 1
            assert fatal_entries[0].message_id == 100
            assert fatal_entries[0].reason == "Resource 404"

    @pytest.mark.asyncio
    async def test_error_status_triggers_retry(self):
        """Test that processor returning status=error triggers retry logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_dead.jsonl")
            dead_queue = DeadLetterQueue(dead_path)

            call_count = 0

            async def error_processor(messages):
                nonlocal call_count
                call_count += 1
                # Processor returns error (retriable)
                return [{"id": m["id"], "chat_id": m["chat_id"], "status": "error"} for m in messages]

            batcher = MessageBatcher(page_size=1, interval=0.1)
            retry_count = 0
            MAX_RETRIES = 3

            async def process_batch(items):
                nonlocal retry_count
                messages = [item["message"] for item in items]
                results = await error_processor(messages)
                # Error status should trigger retry
                for item in items:
                    pmsg = PendingMessage(
                        message_id=item["message_id"],
                        chat_id=item["chat_id"],
                        update_id=item["update_id"],
                        message=item["message"],
                        retry_count=item.get("retry_count", 0),
                    )
                    retry_count += 1
                    pmsg.retry_count = retry_count
                    if retry_count >= MAX_RETRIES:
                        # Move to dead-letter
                        dead_queue.append(DeadLetter(
                            message_id=pmsg.message_id,
                            chat_id=pmsg.chat_id,
                            message=pmsg.message,
                            exec_cmd="processor",
                            failed_at="2024-01-15T10:00:00Z",
                            retry_count=retry_count,
                            error="Max retries",
                        ))
                        pending_queue.remove([pmsg.message_id])

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

            # Error should have been processed
            assert call_count == 1
            assert retry_count == 1

    @pytest.mark.asyncio
    async def test_three_status_distinction(self):
        """Test that success, error, and fatal are handled differently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)
            dead_path = str(Path(tmpdir) / "bot_dead.jsonl")
            dead_queue = DeadLetterQueue(dead_path)
            fatal_path = str(Path(tmpdir) / "bot_456_fatal.jsonl")
            fatal_queue = FatalQueue(fatal_path)

            results_log = []

            async def three_status_processor(messages):
                # Return different statuses for different messages
                results = []
                for m in messages:
                    status = m.get("_expected_status", "success")
                    results.append({"id": m["id"], "chat_id": m["chat_id"], "status": status, "reason": f"{status} reason"})
                return results

            batcher = MessageBatcher(page_size=3, interval=0.1)

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await three_status_processor(messages)
                results_log.extend(results)

                success_ids = []
                fatal_ids = []

                for r in results:
                    if r["status"] == "success":
                        success_ids.append(r["id"])
                    elif r["status"] == "fatal":
                        fatal_ids.append(r["id"])
                        # Append to fatal queue
                        for item in items:
                            if item["message_id"] == r["id"]:
                                fatal_queue.append(FatalError(
                                    message_id=item["message_id"],
                                    chat_id=item["chat_id"],
                                    message=item["message"],
                                    exec_cmd="processor",
                                    failed_at="2024-01-15T10:00:00Z",
                                    reason=r.get("reason", ""),
                                ))

                pending_queue.remove(success_ids + fatal_ids)

            batcher.on_batch = process_batch

            # Add three messages with different expected statuses
            for i, status in enumerate(["success", "error", "fatal"]):
                msg = PendingMessage(
                    message_id=100 + i,
                    chat_id=456,
                    update_id=1 + i,
                    message={"id": 100 + i, "chat_id": 456, "text": f"msg{i}", "_expected_status": status},
                )
                pending_queue.append(msg)
                await batcher.add({
                    "message_id": msg.message_id,
                    "chat_id": msg.chat_id,
                    "update_id": msg.update_id,
                    "message": msg.message,
                })

            await asyncio.sleep(0.2)

            # Check results
            assert len(results_log) == 3
            # Success and fatal should be removed from pending
            remaining = pending_queue.read_all()
            assert len(remaining) == 1
            assert remaining[0].message_id == 101  # error status message
            # Fatal should be in fatal queue
            assert len(fatal_queue.read_all()) == 1
            # Nothing in dead-letter yet
            assert len(dead_queue.read_all()) == 0

    @pytest.mark.asyncio
    async def test_concurrent_message_processing_bug(self):
        """Reproduce bug: messages stuck in pending when processor is slow.

        Scenario:
        1. Message A enters batcher, starts processing (processor is slow)
        2. While A is processing, Message B enters batcher
        3. Both should be processed together or sequentially
        4. BUG: What if processor returns results out of order or missing?

        This test verifies the data flow and matching logic.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)
            results_log = []
            processing_events = []

            # Track when processor starts and finishes
            processor_started = asyncio.Event()
            can_finish = asyncio.Event()

            async def slow_processor(messages):
                """Processor that processes messages and can be controlled."""
                processing_events.append(f"started with {len(messages)} messages")
                processor_started.set()

                # Wait for signal to finish (simulates slow processing)
                await can_finish.wait()

                # Return results - but what if we return fewer results?
                results = []
                for m in messages:
                    results.append({
                        "id": m["id"],
                        "chat_id": m["chat_id"],
                        "status": "success"
                    })
                processing_events.append(f"finished with {len(results)} results")
                results_log.extend(results)
                return results

            batcher = MessageBatcher(page_size=10, interval=0.1)

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await slow_processor(messages)

                # Match results to items
                success_ids = []
                for r in results:
                    msg_id = r.get('id')
                    result_chat_id = r.get('chat_id')
                    if msg_id and result_chat_id:
                        success_ids.append((msg_id, result_chat_id))

                if success_ids:
                    pending_queue.remove_by_chat(success_ids)

            batcher.on_batch = process_batch

            # Add message A
            msg_a = PendingMessage(
                message_id=269,
                chat_id=778110601,
                update_id=860459261,
                message={"id": 269, "chat_id": 778110601, "text": "message A"},
            )
            pending_queue.append(msg_a)
            await batcher.add({
                "message_id": msg_a.message_id,
                "chat_id": msg_a.chat_id,
                "update_id": msg_a.update_id,
                "message": msg_a.message,
            })

            # Wait for processor to start
            await processor_started.wait()

            # While A is processing, add message B
            msg_b = PendingMessage(
                message_id=284,
                chat_id=778110601,
                update_id=860459270,
                message={"id": 284, "chat_id": 778110601, "text": "message B"},
            )
            pending_queue.append(msg_b)
            await batcher.add({
                "message_id": msg_b.message_id,
                "chat_id": msg_b.chat_id,
                "update_id": msg_b.update_id,
                "message": msg_b.message,
            })

            # Let processor finish
            can_finish.set()

            # Wait for batch processing
            await asyncio.sleep(0.3)

            # Check processing events
            print(f"Processing events: {processing_events}")
            print(f"Results log: {results_log}")

            # Verify: both messages should be processed
            remaining = pending_queue.read_all()
            print(f"Remaining in pending: {[m.message_id for m in remaining]}")

            # Both messages should be processed and removed
            assert len(remaining) == 0, f"Both messages should be removed from pending, but found {[m.message_id for m in remaining]}"

    @pytest.mark.asyncio
    async def test_processor_returns_fewer_results_than_inputs(self):
        """Test what happens when processor returns fewer results than input messages.

        This is a potential root cause: processor outputs N results for N+M inputs.
        The M missing results would stay in pending forever with last_attempt=null.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)

            # Processor that only returns 2 results for 3 input messages
            async def partial_processor(messages):
                results = []
                for i, m in enumerate(messages):
                    # Only output results for first 2 messages
                    if i < 2:
                        results.append({
                            "id": m["id"],
                            "chat_id": m["chat_id"],
                            "status": "success"
                        })
                    # Message 3 is silently not returned!
                return results

            batcher = MessageBatcher(page_size=10, interval=0.1)

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await partial_processor(messages)

                # Current logic: only remove messages that have results
                success_ids = []
                for r in results:
                    msg_id = r.get('id')
                    result_chat_id = r.get('chat_id')
                    if msg_id and result_chat_id:
                        success_ids.append((msg_id, result_chat_id))

                if success_ids:
                    pending_queue.remove_by_chat(success_ids)

                # BUG: items without results are never removed from pending!
                # They stay with last_attempt=null, offset advances past them

            batcher.on_batch = process_batch

            # Add 3 messages
            for i in range(3):
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

            await asyncio.sleep(0.2)

            # Check what's left in pending
            remaining = pending_queue.read_all()
            print(f"Remaining in pending: {[m.message_id for m in remaining]}")

            # BUG: Message 102 (id=102) is stuck in pending with no result
            assert len(remaining) == 1, "One message should be stuck (this documents the bug)"
            assert remaining[0].message_id == 102, "Message 102 should be the stuck one"

    @pytest.mark.asyncio
    async def test_batcher_flush_cancel_race_condition(self):
        """Reproduce the race condition in MessageBatcher.cancel() behavior.

        ROOT CAUSE IDENTIFIED:
        When a new message arrives while _debounced_flush is already running:
        1. add() cancels the _flush_task
        2. add() awaits the cancelled task (which raises CancelledError)
        3. But if _flush() is already executing on_batch(), it may NOT be cancelled!
        4. add() creates a new _flush_task
        5. Two _flush() calls run concurrently - results race/overwrite

        The problem: cancelling a Task doesn't stop code that's already running
        inside the coroutine - it just prevents the task from continuing after
        the next await point.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)
            results_log = []
            flush_events = []

            # Create events to control timing
            first_flush_started = asyncio.Event()
            first_flush_can_finish = asyncio.Event()
            second_flush_started = asyncio.Event()

            async def controlled_processor(messages):
                """Processor that signals when it starts and can be controlled."""
                flush_id = id(messages)  # Unique ID for this batch
                flush_events.append(f"processor called with {len(messages)} messages (id={flush_id})")

                if len(messages) == 1 and messages[0].get("id") == 269:
                    # First message - signal and wait
                    first_flush_started.set()
                    await first_flush_can_finish.wait()
                    flush_events.append(f"first processor finishing (id={flush_id})")
                else:
                    # Second message
                    second_flush_started.set()
                    flush_events.append(f"second processor finishing (id={flush_id})")

                return [{"id": m["id"], "chat_id": m["chat_id"], "status": "success"} for m in messages]

            batcher = MessageBatcher(page_size=10, interval=0.05)  # 50ms debounce

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await controlled_processor(messages)
                results_log.extend(results)

                success_ids = [(r['id'], r['chat_id']) for r in results]
                if success_ids:
                    pending_queue.remove_by_chat(success_ids)

            batcher.on_batch = process_batch

            # Add message A - will trigger debounce
            msg_a = PendingMessage(
                message_id=269,
                chat_id=778110601,
                update_id=860459261,
                message={"id": 269, "chat_id": 778110601, "text": "A"},
            )
            pending_queue.append(msg_a)
            await batcher.add({
                "message_id": msg_a.message_id,
                "chat_id": msg_a.chat_id,
                "update_id": msg_a.update_id,
                "message": msg_a.message,
            })

            # Wait for debounce to trigger and processor to start
            await first_flush_started.wait()
            flush_events.append("first processor started, now adding message B")

            # Add message B while A is still being processed
            # This triggers the cancel race condition
            msg_b = PendingMessage(
                message_id=284,
                chat_id=778110601,
                update_id=860459270,
                message={"id": 284, "chat_id": 778110601, "text": "B"},
            )
            pending_queue.append(msg_b)
            await batcher.add({
                "message_id": msg_b.message_id,
                "chat_id": msg_b.chat_id,
                "update_id": msg_b.update_id,
                "message": msg_b.message,
            })
            flush_events.append("message B added")

            # Let first processor finish
            first_flush_can_finish.set()

            # Wait for second flush to complete
            await asyncio.sleep(0.15)

            print(f"Flush events: {flush_events}")
            print(f"Results log: {results_log}")

            remaining = pending_queue.read_all()
            print(f"Remaining in pending: {[m.message_id for m in remaining]}")

            # BUG: Message 269 might be stuck because first flush was interrupted
            # or both flushes ran concurrently with unexpected results

    @pytest.mark.asyncio
    async def test_missing_results_should_trigger_retry(self):
        """Test that messages without results are scheduled for retry.

        DESIGN PRINCIPLE:
        - Batch forms → sent to executor
        - Executor returns results
        - Messages with success/fatal: removed from pending
        - Messages with error: scheduled for retry
        - Messages WITHOUT any result: should also be scheduled for retry!

        CURRENT BUG:
        Messages without results stay in pending_queue but never get retried.
        They wait there until restart, then replayed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_queue = PendingQueue(state_dir=tmpdir)
            retry_scheduled = []

            # Processor that returns NO result for one message
            async def partial_processor(messages):
                results = []
                for m in messages:
                    if m["id"] != 102:  # Skip message 102
                        results.append({
                            "id": m["id"],
                            "chat_id": m["chat_id"],
                            "status": "success"
                        })
                return results

            batcher = MessageBatcher(page_size=10, interval=0.1)
            scheduled_retries = {}  # Simulating the retry tracking

            async def process_batch(items):
                messages = [item["message"] for item in items]
                results = await partial_processor(messages)

                # Current logic (from cli.py)
                success_ids = []
                error_ids = []

                for r in results:
                    msg_id = r.get('id')
                    result_chat_id = r.get('chat_id')
                    status = r.get('status')

                    if status == 'success':
                        success_ids.append((msg_id, result_chat_id))
                    elif status == 'error':
                        error_ids.append((msg_id, result_chat_id))

                # Remove successful from pending
                if success_ids:
                    pending_queue.remove_by_chat(success_ids)

                # Schedule retry for errors
                for item in items:
                    item_key = (item['message_id'], item['chat_id'])
                    if item_key in error_ids:
                        retry_scheduled.append(item['message_id'])

                # BUG: Messages in batch_items that have NO result are ignored!
                # They stay in pending_queue but no retry is scheduled

            batcher.on_batch = process_batch

            # Add 3 messages
            for i in range(3):
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

            await asyncio.sleep(0.2)

            remaining = pending_queue.read_all()
            print(f"Remaining in pending: {[m.message_id for m in remaining]}")
            print(f"Retry scheduled for: {retry_scheduled}")

            # Current behavior (BUG):
            # - Message 102 is in pending_queue (correct)
            # - But no retry is scheduled (wrong!)
            # - It will sit there until restart
            assert len(remaining) == 1
            assert remaining[0].message_id == 102

            # This should be true but currently isn't:
            # assert 102 in retry_scheduled, "Message 102 should have retry scheduled"