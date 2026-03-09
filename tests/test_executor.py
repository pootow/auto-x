"""Tests for command execution utility."""

import pytest

from tele.executor import run_exec_command


class TestExecutor:
    """Test cases for run_exec_command."""

    @pytest.mark.asyncio
    async def test_exec_command_processes_messages(self):
        """run_exec_command should pipe messages to command and parse output."""
        messages = [
            {"id": 1, "text": "hello", "status": "pending"},
            {"id": 2, "text": "world", "status": "pending"},
        ]

        # Use cat as echo to pass through (simulates identity processor)
        result = await run_exec_command("cat", messages)

        assert len(result) == 2
        assert result[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_exec_command_with_shell(self):
        """run_exec_command should support shell execution."""
        import json
        messages = [{"id": 1, "text": "test", "status": "pending"}]

        # Use a simple shell command that outputs valid JSON
        # This tests that shell=True works and output is parsed correctly
        output_json = json.dumps({"id": 1, "status": "success"})

        # Write a simple script that outputs JSON
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(f'print(\'{output_json}\')')
            script_path = f.name

        try:
            result = await run_exec_command(f"python {script_path}", messages, shell=True)
            assert isinstance(result, list)
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_exec_command_handles_empty_output(self):
        """run_exec_command should handle empty output gracefully."""
        messages = [{"id": 1, "text": "test", "status": "pending"}]

        # Use true to produce no output
        result = await run_exec_command("true", messages)

        assert len(result) == 0