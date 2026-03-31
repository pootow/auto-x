"""Tests for CLI ingest commands.

Tests for:
- --list-sources: List configured sources
- --scan: Scan all sources once
- --process-source: Process specific source
- --ingest: Run ingest daemon

All tests use CliRunner to invoke commands without affecting real state.
"""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from tele.cli import cli


class TestIngestCLI:
    """Tests for ingest CLI commands."""

    def test_list_sources_empty(self):
        """--list-sources with no configured sources should show 'No sources'."""
        runner = CliRunner()

        # Mock config with empty sources
        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--list-sources'])

        assert result.exit_code == 0
        assert "No sources" in result.output

    def test_list_sources_with_sources(self):
        """--list-sources should list configured sources."""
        runner = CliRunner()

        # Mock config with sources
        mock_config = MagicMock()
        mock_source = MagicMock()
        mock_source.processor = "my-processor"
        mock_source.chat_id = 12345
        mock_source.filter = None
        mock_config.sources = {"test_source": mock_source}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--list-sources'])

        assert result.exit_code == 0
        assert "Configured sources:" in result.output
        assert "test_source" in result.output
        assert "my-processor" in result.output

    def test_list_sources_with_filter(self):
        """--list-sources should show filter if configured."""
        runner = CliRunner()

        # Mock config with source that has a filter
        mock_config = MagicMock()
        mock_source = MagicMock()
        mock_source.processor = "processor"
        mock_source.chat_id = 12345
        mock_source.filter = "contains('test')"
        mock_config.sources = {"filtered_source": mock_source}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--list-sources'])

        assert result.exit_code == 0
        assert "filter: contains('test')" in result.output

    def test_scan_command_exists(self):
        """--scan command should be recognized."""
        runner = CliRunner()

        # Mock config with empty sources (to prevent actual processing)
        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--scan'])

        # Should not show "no such option" error
        assert "no such option" not in result.output.lower()
        assert result.exit_code == 0

    def test_scan_no_sources(self):
        """--scan with no sources should show appropriate message."""
        runner = CliRunner()

        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--scan'])

        assert result.exit_code == 0
        assert "No sources" in result.output

    def test_scan_with_sources_no_files(self, tmp_path):
        """--scan with sources but no incoming files should process 0 messages."""
        runner = CliRunner()

        # Mock config with a source
        mock_config = MagicMock()
        mock_source = MagicMock()
        mock_source.processor = "processor"
        mock_source.chat_id = 12345
        mock_config.sources = {"test_source": mock_source}

        # Mock state manager to return empty files
        with patch('tele.cli.load_config', return_value=mock_config):
            with patch('tele.cli.SourceStateManager') as mock_state_mgr_class:
                mock_state_mgr = MagicMock()
                mock_state_mgr.state_dir = tmp_path
                mock_state_mgr.get_source_dir.return_value = tmp_path / "test_source"
                mock_state_mgr.get_incoming_files.return_value = []
                mock_state_mgr_class.return_value = mock_state_mgr

                result = runner.invoke(cli, ['--scan'])

        assert result.exit_code == 0
        assert "Scan complete" in result.output
        assert "0 messages" in result.output

    def test_process_source_requires_source_name(self):
        """--process-source without a value should fail."""
        runner = CliRunner()

        result = runner.invoke(cli, ['--process-source'])

        # Should fail - missing required argument
        assert result.exit_code != 0 or "requires" in result.output.lower() or "Error" in result.output

    def test_process_source_not_in_config(self):
        """--process-source with unknown source should fail."""
        runner = CliRunner()

        # Mock config with no matching source
        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--process-source', 'unknown_source'])

        assert result.exit_code != 0
        assert "not found" in result.output

    def test_process_source_exists_in_config(self, tmp_path):
        """--process-source with valid source should work."""
        runner = CliRunner()

        # Mock config with the source
        mock_config = MagicMock()
        mock_source = MagicMock()
        mock_source.processor = "echo"  # Use echo as safe processor
        mock_source.chat_id = 12345
        mock_config.sources = {"my_source": mock_source}

        # Mock the state manager and consumer
        with patch('tele.cli.load_config', return_value=mock_config):
            with patch('tele.cli.SourceStateManager') as mock_state_mgr_class:
                mock_state_mgr = MagicMock()
                mock_state_mgr.state_dir = tmp_path
                mock_state_mgr.get_source_dir.return_value = tmp_path / "my_source"
                mock_state_mgr_class.return_value = mock_state_mgr

                with patch('tele.cli.SourceConsumer') as mock_consumer_class:
                    mock_consumer = MagicMock()
                    mock_consumer.consume_available.return_value = []  # No messages
                    mock_consumer_class.return_value = mock_consumer

                    result = runner.invoke(cli, ['--process-source', 'my_source'])

        assert result.exit_code == 0
        assert "Processed 0 messages" in result.output

    def test_ingest_command_exists(self):
        """--ingest command should be recognized."""
        runner = CliRunner()

        # Mock config with empty sources (to prevent daemon starting)
        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--ingest'])

        # Should not show "unknown option" error
        assert "unknown option" not in result.output.lower()
        # Should exit cleanly (no sources configured)
        assert result.exit_code == 0

    def test_ingest_no_sources(self):
        """--ingest with no sources should show message and exit."""
        runner = CliRunner()

        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--ingest'])

        assert result.exit_code == 0
        assert "No sources configured" in result.output

    def test_ingest_starts_daemon(self, tmp_path):
        """--ingest should start daemon loop."""
        runner = CliRunner()

        # Mock config with a source
        mock_config = MagicMock()
        mock_source = MagicMock()
        mock_source.processor = "processor"
        mock_source.chat_id = 12345
        mock_config.sources = {"test_source": mock_source}

        # Mock ingest config
        mock_ingest = MagicMock()
        mock_ingest.poll_interval = 30.0
        mock_ingest.watch_enabled = False  # Disable watchdog for test
        mock_config.ingest = mock_ingest

        with patch('tele.cli.load_config', return_value=mock_config):
            with patch('tele.cli.SourceStateManager') as mock_state_mgr_class:
                mock_state_mgr = MagicMock()
                mock_state_mgr.state_dir = tmp_path
                mock_state_mgr.get_source_dir.return_value = tmp_path / "test_source"
                mock_state_mgr_class.return_value = mock_state_mgr

                # Create a real SourceWatcher instance with mocked async methods
                with patch('tele.cli.SourceWatcher.wait_for_event', new=AsyncMock(side_effect=KeyboardInterrupt)):
                    with patch('tele.cli.SourceWatcher.start_watchdog', return_value=False):
                        with patch('tele.cli.SourceWatcher.stop_watchdog'):
                            with patch('tele.cli.SourceWatcher.get_sources_with_changes', return_value=set()):
                                result = runner.invoke(cli, ['--ingest'])

        assert result.exit_code == 0
        assert "Ingest daemon started" in result.output
        assert "test_source" in result.output


class TestIngestCLIIntegration:
    """Integration tests for ingest CLI commands."""

    def test_cli_help_includes_ingest_options(self):
        """CLI help should show ingest-related options."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])

        assert result.exit_code == 0
        assert "--ingest" in result.output
        assert "--scan" in result.output
        assert "--process-source" in result.output
        assert "--list-sources" in result.output

    def test_list_sources_does_not_require_other_options(self):
        """--list-sources should work standalone without --chat."""
        runner = CliRunner()

        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--list-sources'])

        # Should NOT complain about missing --chat
        assert "Chat name or ID is required" not in result.output
        assert result.exit_code == 0

    def test_scan_does_not_require_chat(self):
        """--scan should work standalone without --chat."""
        runner = CliRunner()

        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--scan'])

        # Should NOT complain about missing --chat
        assert "Chat name or ID is required" not in result.output
        assert result.exit_code == 0

    def test_ingest_does_not_require_chat(self):
        """--ingest should work standalone without --chat."""
        runner = CliRunner()

        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--ingest'])

        # Should NOT complain about missing --chat
        assert "Chat name or ID is required" not in result.output
        assert result.exit_code == 0

    def test_process_source_does_not_require_chat(self):
        """--process-source should work standalone without --chat."""
        runner = CliRunner()

        mock_config = MagicMock()
        mock_config.sources = {}

        with patch('tele.cli.load_config', return_value=mock_config):
            result = runner.invoke(cli, ['--process-source', 'any_source'])

        # Should NOT complain about missing --chat (will fail for different reason)
        assert "Chat name or ID is required" not in result.output


class TestProcessSourceMessages:
    """Tests for process_source_messages helper function."""

    @pytest.mark.asyncio
    async def test_process_source_messages_no_messages(self, tmp_path):
        """process_source_messages should return 0 when no messages available."""
        from tele.cli import process_source_messages

        # Mock config
        mock_config = MagicMock()
        mock_source = MagicMock()
        mock_source.processor = "processor"
        mock_source.chat_id = 12345
        mock_config.sources = {"test": mock_source}

        # Mock consumer that returns no messages
        with patch('tele.cli.SourceStateManager') as mock_state_mgr_class:
            mock_state_mgr = MagicMock()
            mock_state_mgr.state_dir = tmp_path
            mock_state_mgr_class.return_value = mock_state_mgr

            with patch('tele.cli.SourceConsumer') as mock_consumer_class:
                mock_consumer = MagicMock()
                mock_consumer.consume_available.return_value = []
                mock_consumer_class.return_value = mock_consumer

                result = await process_source_messages(mock_config, "test")

        assert result == 0

    @pytest.mark.asyncio
    async def test_process_source_messages_with_messages(self, tmp_path):
        """process_source_messages should process messages and return count."""
        from tele.cli import process_source_messages

        # Mock config
        mock_config = MagicMock()
        mock_source = MagicMock()
        mock_source.processor = "echo"  # Use echo as processor
        mock_source.chat_id = 12345
        mock_config.sources = {"test": mock_source}

        # Messages to process
        messages = [
            {"id": 1, "text": "msg1"},
            {"id": 2, "text": "msg2"},
        ]

        # Mock consumer that returns messages
        with patch('tele.cli.SourceStateManager') as mock_state_mgr_class:
            mock_state_mgr = MagicMock()
            mock_state_mgr.state_dir = tmp_path
            mock_state_mgr_class.return_value = mock_state_mgr

            with patch('tele.cli.SourceConsumer') as mock_consumer_class:
                mock_consumer = MagicMock()
                mock_consumer.consume_available.return_value = messages
                mock_consumer_class.return_value = mock_consumer

                # Mock run_exec_command to return success results
                with patch('tele.cli.run_exec_command', new_callable=AsyncMock) as mock_exec:
                    mock_exec.return_value = [
                        {"id": 1, "chat_id": 12345, "status": "success"},
                        {"id": 2, "chat_id": 12345, "status": "success"},
                    ]

                    result = await process_source_messages(mock_config, "test")

        assert result == 2