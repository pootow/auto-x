"""Tests for the logging module."""

import logging
import os
import pytest

from tele.log import (
    setup_logging,
    get_logger,
    get_log_level_name,
    setup_processor_logging,
    TRACE,
)


class TestGetLogLevelName:
    """Tests for get_log_level_name function."""

    def test_verbosity_0_returns_warning(self):
        assert get_log_level_name(0) == "WARNING"

    def test_verbosity_1_returns_info(self):
        assert get_log_level_name(1) == "INFO"

    def test_verbosity_2_returns_debug(self):
        assert get_log_level_name(2) == "DEBUG"

    def test_verbosity_3_returns_trace(self):
        assert get_log_level_name(3) == "TRACE"

    def test_verbosity_4_capped_at_trace(self):
        assert get_log_level_name(4) == "TRACE"

    def test_verbosity_10_capped_at_trace(self):
        assert get_log_level_name(10) == "TRACE"


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

    def test_sets_trace_level_with_vvv(self):
        logger = setup_logging(3)
        assert logger.level == TRACE

    def test_logger_name_is_tele(self):
        logger = setup_logging(0)
        assert logger.name == "tele"

    def test_handler_outputs_to_stderr(self, capsys):
        logger = setup_logging(1)  # INFO level
        logger.info("Test message")
        captured = capsys.readouterr()
        assert "[INFO] Test message" in captured.err
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

    def test_uses_env_var_trace(self, monkeypatch):
        monkeypatch.setenv("TELE_LOG_LEVEL", "TRACE")
        logger = setup_processor_logging()
        assert logger.level == TRACE

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
        assert "[INFO] Processor message" in captured.err
        assert captured.out == ""  # Nothing to stdout


class TestTraceLevel:
    """Tests for TRACE log level."""

    def test_trace_is_below_debug(self):
        assert TRACE < logging.DEBUG

    def test_trace_value_is_5(self):
        assert TRACE == 5

    def test_trace_level_name_registered(self):
        assert logging.getLevelName(TRACE) == "TRACE"