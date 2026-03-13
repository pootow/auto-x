"""Tests for command execution utility."""

import pytest
import json
import tempfile
import os

from tele.executor import run_exec_command


class TestExecutor:
    """Test cases for run_exec_command."""

    @pytest.mark.asyncio
    async def test_exec_command_processes_messages(self):
        """run_exec_command should pipe messages to command and parse output."""
        messages = [
            {"id": 1, "chat_id": 123, "text": "hello"},
            {"id": 2, "chat_id": 123, "text": "world"},
        ]

        # Create a processor script
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    msg = json.loads(line)
    msg["status"] = "success"
    print(json.dumps(msg))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(result) == 2
            assert result[0]["id"] == 1
            assert result[0]["chat_id"] == 123
            assert result[0]["status"] == "success"
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_exec_command_defaults_to_failed(self):
        """Processor output without status should default to failed."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Create a processor that outputs without status
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    msg = json.loads(line)
    # Output without status - should default to failed
    print(json.dumps({"id": msg["id"], "chat_id": msg["chat_id"]}))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(result) == 1
            assert result[0]["status"] == "failed"
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_exec_command_requires_id_and_chat_id(self):
        """Output without id or chat_id should be skipped."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Create a processor that outputs without chat_id
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
for line in sys.stdin:
    print(json.dumps({"id": 1, "status": "success"}))
''')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(result) == 0
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_exec_command_handles_empty_output(self):
        """run_exec_command should handle empty output gracefully."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Use true to produce no output
        result = await run_exec_command("true", messages)

        assert len(result) == 0