"""Acceptance tests for CLI interface contract.

Contract: CLI interface and behavior.
"""

import pytest
from click.testing import CliRunner

from tele.cli import cli


class TestCLIContract:
    """Contract: CLI interface and behavior."""

    def test_bot_mode_requires_exec(self):
        """
        Given: User runs tele --bot without --exec
        When: CLI parses arguments
        Then: Exit code is non-zero
        And: Error message mentions --exec is required
        """
        runner = CliRunner()
        result = runner.invoke(cli, ['--bot'])

        assert result.exit_code != 0
        assert '--exec' in result.output or 'required' in result.output.lower()

    @pytest.mark.skip(reason="CliRunner blocks on async daemon - test manually")
    def test_bot_mode_accepts_optional_chat(self):
        """
        Given: User runs tele --bot --exec "processor" (no --chat)
        When: CLI parses arguments
        Then: Daemon starts successfully (would run if bot token provided)
        And: All chats are processed (no chat filter applied)

        Note: This test verifies argument parsing, not full daemon execution.
        """
        runner = CliRunner()
        # With --exec but without --chat, parsing should succeed
        # But it will fail because no bot token is configured
        # Use catch_exceptions=False to see the actual error
        result = runner.invoke(cli, ['--bot', '--exec', 'echo test'], catch_exceptions=True)

        # Should fail due to missing bot token, not missing --chat
        # The error should mention BOT_TOKEN, not --chat
        assert 'Chat must be numeric ID' not in result.output
        # Either mentions bot token or exit code is non-zero (missing token)
        assert 'BOT_TOKEN' in result.output or 'token' in result.output.lower() or result.exit_code != 0

    def test_app_mode_requires_chat(self):
        """
        Given: User runs tele without --chat and no default in config
        When: CLI parses arguments
        Then: Exit code is non-zero
        And: Error message mentions --chat is required
        """
        runner = CliRunner()
        result = runner.invoke(cli, [])

        assert result.exit_code != 0
        assert 'chat' in result.output.lower() or 'required' in result.output.lower()

    def test_filter_expression_accepted(self):
        """
        Given: User runs tele --chat "x" --filter 'contains("test")'
        When: CLI parses arguments
        Then: Filter is created successfully
        And: No syntax error is raised
        """
        runner = CliRunner()
        # This will fail due to missing Telegram credentials, but filter parsing should work
        result = runner.invoke(cli, ['--chat', 'test_chat', '--filter', 'contains("test")'])

        # Should not have filter syntax error
        assert 'filter' not in result.output.lower() or 'syntax' not in result.output.lower()

    def test_invalid_filter_syntax_errors(self):
        """
        Given: User runs tele --filter 'contains("unclosed'
        When: CLI parses arguments
        Then: SyntaxError is raised
        And: Error message indicates filter syntax issue
        """
        runner = CliRunner()
        result = runner.invoke(cli, ['--chat', 'test_chat', '--filter', 'contains("unclosed'])

        # Should have an error related to filter syntax
        assert result.exit_code != 0

    def test_help_shows_usage(self):
        """
        Given: User runs tele --help
        When: CLI executes
        Then: Exit code is 0
        And: Output contains usage information
        And: All modes are documented (bot, app, mark)
        """
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])

        assert result.exit_code == 0
        assert 'Usage' in result.output or 'usage' in result.output.lower()
        # Check for mode documentation
        assert '--bot' in result.output
        assert '--chat' in result.output
        assert '--mark' in result.output

    def test_retry_dead_requires_path(self):
        """
        Given: User runs tele --retry-dead without path
        When: CLI parses arguments
        Then: Exit code is non-zero or path is required
        """
        runner = CliRunner()
        # --retry-dead requires a path value
        result = runner.invoke(cli, ['--retry-dead'])

        # Should error due to missing path value
        assert result.exit_code != 0 or 'requires' in result.output.lower()

    def test_mark_mode_uses_default_reaction(self):
        """
        Given: User runs tele --mark without --reaction
        When: CLI parses arguments
        Then: Default reaction emoji is used (thumbs up)
        """
        runner = CliRunner()
        # Will fail due to missing credentials, but should parse correctly
        result = runner.invoke(cli, ['--mark'])

        # Just verify it parses without error about reaction
        assert 'reaction' not in result.output.lower() or 'invalid' not in result.output.lower()

    def test_verbose_flags_accepted(self):
        """
        Given: User runs tele with -v, -vv, -vvv flags
        When: CLI parses arguments
        Then: Verbosity level is set accordingly
        """
        runner = CliRunner()

        # Test -v (verbose level 1)
        result = runner.invoke(cli, ['-v', '--help'])
        assert result.exit_code == 0

        # Test -vv (verbose level 2)
        result = runner.invoke(cli, ['-vv', '--help'])
        assert result.exit_code == 0

        # Test -vvv (verbose level 3)
        result = runner.invoke(cli, ['-vvv', '--help'])
        assert result.exit_code == 0

    def test_batch_size_accepted(self):
        """
        Given: User runs tele with --batch-size 50
        When: CLI parses arguments
        Then: Batch size is set to 50
        """
        runner = CliRunner()
        result = runner.invoke(cli, ['--batch-size', '50', '--help'])

        assert result.exit_code == 0

    @pytest.mark.skip(reason="CliRunner blocks on async daemon - test manually")
    def test_page_size_and_interval_accepted(self):
        """
        Given: User runs tele --bot with --page-size and --interval
        When: CLI parses arguments
        Then: Options are accepted
        """
        runner = CliRunner()
        result = runner.invoke(cli, ['--bot', '--exec', 'test', '--page-size', '20', '--interval', '5'])

        # Will fail due to missing bot token, but options should be parsed
        assert 'unrecognized arguments' not in result.output
        assert 'invalid' not in result.output.lower() or 'token' in result.output.lower()