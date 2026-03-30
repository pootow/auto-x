"""Tests for the logging module."""

import logging
import os
import pytest

from tele.log import (
    setup_logging,
    get_logger,
    get_log_level_name,
    setup_processor_logging,
    DATAFLOW,
    ColoredFormatter,
    COMPONENT_MAP,
)


class TestGetLogLevelName:
    """Tests for get_log_level_name function."""

    def test_verbosity_0_returns_warning(self):
        assert get_log_level_name(0) == "WARNING"

    def test_verbosity_1_returns_info(self):
        assert get_log_level_name(1) == "INFO"

    def test_verbosity_2_returns_debug(self):
        assert get_log_level_name(2) == "DEBUG"

    def test_verbosity_3_returns_dataflow(self):
        assert get_log_level_name(3) == "DATAFLOW"

    def test_verbosity_4_capped_at_dataflow(self):
        assert get_log_level_name(4) == "DATAFLOW"

    def test_verbosity_10_capped_at_dataflow(self):
        assert get_log_level_name(10) == "DATAFLOW"


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_sets_warning_level_by_default(self):
        logger = setup_logging(0)
        assert logger.level == logging.WARNING

    def test_sets_info_level_with_v(self):
        logger = setup_logging(1)
        assert logger.level == logging.INFO

    def test_sets_debug_level_with_vv(self):
        logger = setup_logging(2)
        assert logger.level == logging.DEBUG

    def test_sets_dataflow_level_with_vvv(self):
        logger = setup_logging(3)
        assert logger.level == DATAFLOW

    def test_logger_name_is_tele(self):
        logger = setup_logging(0)
        assert logger.name == "tele"

    def test_handler_outputs_to_stderr(self, capsys):
        logger = setup_logging(1)  # INFO level
        logger.info("Test message")
        captured = capsys.readouterr()
        assert "Test message" in captured.err
        assert captured.out == ""  # Nothing to stdout

    def test_warning_level_filters_info(self, capsys):
        logger = setup_logging(0)  # WARNING level
        logger.info("This should be filtered")
        logger.warning("This should appear")
        captured = capsys.readouterr()
        assert "This should be filtered" not in captured.err
        assert "This should appear" in captured.err


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_tele_logger_by_default(self):
        logger = get_logger()
        assert logger.name == "tele"

    def test_returns_named_logger(self):
        logger = get_logger("tele.bot")
        assert logger.name == "tele.bot"

    def test_returns_tele_child_logger(self):
        logger = get_logger("tele.client")
        assert logger.name == "tele.client"


class TestSetupProcessorLogging:
    """Tests for setup_processor_logging function."""

    def test_defaults_to_warning_without_env(self, monkeypatch):
        monkeypatch.delenv("TELE_LOG_LEVEL", raising=False)
        logger = setup_processor_logging()
        assert logger.level == logging.WARNING

    def test_uses_env_var_warning(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "WARNING")
        logger = setup_processor_logging()
        assert logger.level == logging.WARNING

    def test_uses_env_var_info(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "INFO")
        logger = setup_processor_logging()
        assert logger.level == logging.INFO

    def test_uses_env_var_debug(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "DEBUG")
        logger = setup_processor_logging()
        assert logger.level == logging.DEBUG

    def test_uses_env_var_dataflow(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "DATAFLOW")
        logger = setup_processor_logging()
        assert logger.level == DATAFLOW

    def test_uses_env_var_error(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "ERROR")
        logger = setup_processor_logging()
        assert logger.level == logging.ERROR

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "debug")
        logger = setup_processor_logging()
        assert logger.level == logging.DEBUG

    def test_invalid_level_defaults_to_warning(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "INVALID")
        logger = setup_processor_logging()
        assert logger.level == logging.WARNING

    def test_outputs_to_stderr_only(self, monkeypatch, capsys):
        monkeypatch.setenv("TELE_LOG_LEVEL", "INFO")
        logger = setup_processor_logging()
        logger.info("Processor message")
        captured = capsys.readouterr()
        assert "Processor message" in captured.err
        assert captured.out == ""  # Nothing to stdout


class TestDataflowLevel:
    """Tests for DATAFLOW log level."""

    def test_dataflow_is_between_debug_and_info(self):
        assert logging.DEBUG < DATAFLOW < logging.INFO

    def test_dataflow_value_is_15(self):
        assert DATAFLOW == 15

    def test_dataflow_level_name_registered(self):
        assert logging.getLevelName(DATAFLOW) == "DATAFLOW"

    def test_dataflow_shows_json_output(self, capsys):
        logger = setup_logging(3)  # DATAFLOW level
        logger.log(DATAFLOW, '{"id": 1, "chat_id": 123}')
        captured = capsys.readouterr()
        assert '{"id": 1, "chat_id": 123}' in captured.err

    def test_debug_shows_dataflow(self, capsys):
        logger = setup_logging(2)  # DEBUG level
        logger.log(DATAFLOW, "This should appear")
        logger.debug("This should also appear")
        captured = capsys.readouterr()
        assert "This should appear" in captured.err
        assert "This should also appear" in captured.err

    def test_info_filters_dataflow(self, capsys):
        logger = setup_logging(1)  # INFO level
        logger.log(DATAFLOW, "This should be filtered")
        logger.info("This should appear")
        captured = capsys.readouterr()
        assert "This should be filtered" not in captured.err
        assert "This should appear" in captured.err


class TestColoredFormatter:
    """Tests for ColoredFormatter."""

    def test_format_produces_fixed_width_output(self, monkeypatch):
        """Test that format produces correct fixed-width output."""
        # Mock PID
        monkeypatch.setattr(os, 'getpid', lambda: 12345)

        formatter = ColoredFormatter(
            process_name='tele',
            component='poll'
        )

        # Create a log record
        record = logging.LogRecord(
            name='tele.bot',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Connected to Telegram',
            args=(),
            exc_info=None
        )

        result = formatter.format(record)

        # Should match format: [tele ][12345][poll ][INFO ] YYYY-MM-DD HH:MM:SS | Connected to Telegram
        # Note: process_name is padded to 5 chars, so 'tele' becomes 'tele '
        assert '[tele ]' in result
        assert '[12345]' in result
        assert '[poll ]' in result
        assert '[INFO ]' in result
        assert ' | Connected to Telegram' in result

    def test_format_warn_level(self, monkeypatch):
        """Test WARN level formatting."""
        monkeypatch.setattr(os, 'getpid', lambda: 12345)

        formatter = ColoredFormatter(process_name='tele', component='poll')

        record = logging.LogRecord(
            name='tele.bot',
            level=logging.WARNING,
            pathname='test.py',
            lineno=1,
            msg='Retry failed',
            args=(),
            exc_info=None
        )

        result = formatter.format(record)
        assert '[WARN ]' in result

    def test_format_dataflow_level(self, monkeypatch):
        """Test DATAFLOW level shows INFO with [flow ] prefix."""
        monkeypatch.setattr(os, 'getpid', lambda: 12345)

        formatter = ColoredFormatter(process_name='tele', component='exec')

        # DATAFLOW level value is 15
        record = logging.LogRecord(
            name='tele.executor',
            level=15,  # DATAFLOW
            pathname='test.py',
            lineno=1,
            msg='{"id": 123}',
            args=(),
            exc_info=None
        )
        record.levelname = 'DATAFLOW'

        result = formatter.format(record)

        # DATAFLOW should display as INFO with [flow ] prefix
        assert '[INFO ]' in result
        assert '[flow ] {"id": 123}' in result