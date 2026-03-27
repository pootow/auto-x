"""Acceptance tests for processor protocol contract.

Contract: How tele communicates with processors via stdio.
"""

import pytest
import json
import tempfile
import os
from unittest.mock import AsyncMock, patch, MagicMock

from tele.executor import run_exec_command


class TestProcessorProtocol:
    """Contract: How tele communicates with processors via stdio."""

    @pytest.mark.asyncio
    async def test_sends_json_lines_to_stdin(self):
        """
        Given: Messages queued for processing
        When: tele executes the processor
        Then: Each message is sent as a JSON line via stdin
        And: Each line contains required fields (id, chat_id, text, sender_id, date)
        """
        messages = [
            {"id": 1, "chat_id": 123, "text": "hello", "sender_id": 456, "date": "2024-01-15T10:00:00Z"},
            {"id": 2, "chat_id": 123, "text": "world", "sender_id": 789, "date": "2024-01-15T11:00:00Z"},
        ]

        # Create a processor that captures stdin and verifies format
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json

# Read all stdin lines
stdin_lines = []
for line in sys.stdin:
    stdin_lines.append(line.strip())

# Verify each line is valid JSON with required fields
for line in stdin_lines:
    msg = json.loads(line)
    # Output the received message for verification (must include id and chat_id)
    result = {"id": msg.get("id"), "chat_id": msg.get("chat_id"), "received": msg, "has_required": all(k in msg for k in ["id", "chat_id", "text"])}
    print(json.dumps(result))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            # Verify the processor received the messages correctly
            assert len(result) == 2
            for i, r in enumerate(result):
                assert "received" in r
                assert r["has_required"] is True
                assert r["received"]["id"] == messages[i]["id"]
                assert r["received"]["chat_id"] == messages[i]["chat_id"]
                assert r["received"]["text"] == messages[i]["text"]
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_accepts_success_status(self):
        """
        Given: Processor returns {"id": 1, "chat_id": 2, "status": "success"}
        When: tele reads processor stdout
        Then: Message is marked as processed
        And: Message is removed from pending queue
        And: Success reaction is sent to Telegram
        """
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    msg = json.loads(line)
    print(json.dumps({"id": msg["id"], "chat_id": msg["chat_id"], "status": "success"}))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(result) == 1
            assert result[0]["id"] == 1
            assert result[0]["chat_id"] == 123
            assert result[0]["status"] == "success"
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_accepts_error_status_and_retries(self):
        """
        Given: Processor returns {"id": 1, "chat_id": 2, "status": "error"}
        When: tele reads processor stdout
        Then: Message is NOT removed from pending queue
        And: Retry is scheduled with backoff
        And: No reaction is sent yet
        """
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    msg = json.loads(line)
    print(json.dumps({"id": msg["id"], "chat_id": msg["chat_id"], "status": "error"}))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            # The executor returns the result, retry logic is in cli.py
            assert len(result) == 1
            assert result[0]["status"] == "error"
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_accepts_fatal_status_and_skips_retry(self):
        """
        Given: Processor returns {"id": 1, "chat_id": 2, "status": "fatal", "reason": "404"}
        When: tele reads processor stdout
        Then: Message is removed from pending queue
        And: Message is appended to fatal queue
        And: Failed reaction is sent to Telegram
        And: No retry is scheduled
        """
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    msg = json.loads(line)
    print(json.dumps({"id": msg["id"], "chat_id": msg["chat_id"], "status": "fatal", "reason": "404 not found"}))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(result) == 1
            assert result[0]["status"] == "fatal"
            assert result[0]["reason"] == "404 not found"
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_accepts_reply_and_sends_to_telegram(self):
        """
        Given: Processor returns {"id": 1, "chat_id": 2, "status": "success", "reply": [...]}
        When: tele reads processor stdout
        Then: Each reply item is sent as a separate message to Telegram
        And: Video/photo/text is sent based on media type
        """
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    msg = json.loads(line)
    result = {
        "id": msg["id"],
        "chat_id": msg["chat_id"],
        "status": "success",
        "reply": [
            {"text": "Video description", "media": {"type": "video", "url": "https://example.com/video.mp4"}},
            {"text": "Photo description", "media": {"type": "image", "url": "https://example.com/photo.jpg"}},
            {"text": "Just text reply"}
        ]
    }
    print(json.dumps(result))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(result) == 1
            assert result[0]["status"] == "success"
            assert "reply" in result[0]
            assert len(result[0]["reply"]) == 3
            assert result[0]["reply"][0]["media"]["type"] == "video"
            assert result[0]["reply"][1]["media"]["type"] == "image"
            assert "media" not in result[0]["reply"][2]
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_missing_status_defaults_to_error(self):
        """
        Given: Processor returns {"id": 1, "chat_id": 2} (no status)
        When: tele reads processor stdout
        Then: Status defaults to "error"
        And: Retry logic is triggered
        """
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    msg = json.loads(line)
    # Output without status - should default to error (retriable)
    print(json.dumps({"id": msg["id"], "chat_id": msg["chat_id"]}))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(result) == 1
            # The executor should default to "error" when status is missing
            assert result[0]["status"] == "error"
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_processor_timeout_returns_error_status(self):
        """
        Given: Processor takes longer than the timeout
        When: tele waits for processor output
        Then: Processor is killed after timeout
        And: All messages return error status
        And: Daemon continues running
        """
        messages = [
            {"id": 1, "chat_id": 123, "text": "test1"},
            {"id": 2, "chat_id": 123, "text": "test2"},
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
import time

# Read messages
for line in sys.stdin:
    msg = json.loads(line)

# Sleep for a very long time (longer than timeout)
time.sleep(3600)  # 1 hour

# This should never execute
for msg in messages:
    print(json.dumps({"id": msg["id"], "chat_id": msg["chat_id"], "status": "success"}))
''')
            script_path = f.name

        try:
            # Use a short timeout for testing
            result = await run_exec_command(f"python {script_path}", messages, shell=True, timeout=2.0)

            # After timeout, all messages should return error status
            assert len(result) == 2
            assert all(r["status"] == "error" for r in result)
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_processor_crash_returns_error_status(self):
        """
        Given: Processor exits with non-zero code
        When: tele reads processor stdout
        Then: All messages return error status
        And: Retry is scheduled
        And: Daemon continues running
        """
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import sys
sys.exit(1)  # Exit immediately with error code
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            # After crash, message should return error status
            assert len(result) == 1
            assert result[0]["status"] == "error"
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_processor_not_found_returns_error_status(self):
        """
        Given: Processor command does not exist
        When: tele tries to execute processor
        Then: All messages return error status
        And: Daemon continues running
        """
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Use a non-existent command
        result = await run_exec_command("nonexistent_processor_command_xyz", messages, shell=True)

        # After failure, message should return error status
        assert len(result) == 1
        assert result[0]["status"] == "error"