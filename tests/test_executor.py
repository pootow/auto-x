"""Tests for command execution utility."""

import pytest
import json
import tempfile
import os

from tele.executor import run_exec_command, infer_level, format_processor_line


class TestInferLevel:
    """Tests for level inference from processor output."""

    def test_error_keywords(self):
        assert infer_level("Error: something failed") == "ERROR"
        assert infer_level("FAILED to process") == "ERROR"
        assert infer_level("Exception occurred") == "ERROR"

    def test_warn_keywords(self):
        assert infer_level("Warning: check this") == "WARN "
        assert infer_level("WARN: deprecated") == "WARN "

    def test_default_info(self):
        assert infer_level("Processing message") == "INFO "
        assert infer_level("Download complete") == "INFO "


class TestFormatProcessorLine:
    """Tests for formatting processor output lines."""

    def test_format_basic_line(self, monkeypatch):
        monkeypatch.setattr('os.getpid', lambda: 12345)

        # Simulate processor output interception
        result = format_processor_line("ytdlp", "Download started", "INFO ")
        assert '[ytdlp]' in result
        assert '[INFO ]' in result
        assert 'Download started' in result

    def test_format_error_line(self, monkeypatch):
        monkeypatch.setattr('os.getpid', lambda: 12345)

        result = format_processor_line("ytdlp", "Error: download failed", "ERROR")
        assert '[ytdlp]' in result
        assert '[ERROR]' in result

    def test_format_with_level_none_infers_error(self, monkeypatch):
        """Test that level=None triggers level inference from content."""
        monkeypatch.setattr('os.getpid', lambda: 12345)

        # Pass level=None - should infer ERROR from "Error:" in content
        result = format_processor_line("ytdlp", "Error: download failed", None)
        assert '[ytdlp]' in result
        assert '[ERROR]' in result


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
    async def test_exec_command_defaults_to_error(self):
        """Processor output without status should default to error (retriable)."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Create a processor that outputs without status
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
            assert result[0]["status"] == "error"
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


class TestRunExecCommandStderr:
    """Tests for stderr interception in run_exec_command."""

    @pytest.mark.asyncio
    async def test_stderr_is_intercepted_and_formatted(self, capsys):
        """Test that processor stderr output is intercepted and formatted."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Command that outputs to stderr
        cmd = 'python -c "import sys; print(\'test stderr output\', file=sys.stderr)"'

        results = await run_exec_command(cmd, messages, shell=True)

        # No stdout JSON means empty results (consistent with existing behavior)
        assert len(results) == 0

        # Check that stderr was captured and formatted
        captured = capsys.readouterr()
        # The stderr should contain the formatted output with [pytho] prefix (truncated)
        assert 'test stderr output' in captured.err

    @pytest.mark.asyncio
    async def test_stderr_with_valid_stdout_json(self, capsys):
        """Test that stdout JSON Lines are still parsed correctly when stderr exists."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Use a script file to avoid quoting issues on Windows
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
import sys
import json
print('stderr msg', file=sys.stderr)
print(json.dumps({"id": 1, "chat_id": 123, "status": "success"}))
''')
            script_path = f.name

        try:
            results = await run_exec_command(f"python {script_path}", messages, shell=True)

            assert len(results) == 1
            assert results[0]['status'] == 'success'

            # Stderr should still be captured
            captured = capsys.readouterr()
            assert 'stderr msg' in captured.err
        finally:
            os.unlink(script_path)

    @pytest.mark.asyncio
    async def test_stderr_multiline_formatted_individually(self, capsys):
        """Test that multiple stderr lines are formatted individually."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Command that outputs multiple stderr lines
        cmd = 'python -c "import sys; print(\'line1\', file=sys.stderr); print(\'line2\', file=sys.stderr)"'

        results = await run_exec_command(cmd, messages, shell=True)

        captured = capsys.readouterr()
        # Both lines should appear in stderr output
        assert 'line1' in captured.err
        assert 'line2' in captured.err