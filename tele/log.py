"""Logging utilities for tele and processors."""

import logging
import os
import sys

# TRACE level (below DEBUG)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def setup_logging(verbosity: int = 0) -> logging.Logger:
    """Setup logging based on verbosity level.

    Args:
        verbosity: Number of -v flags (0-3)

    Returns:
        Configured logger for tele
    """
    levels = [logging.WARNING, logging.INFO, logging.DEBUG, TRACE]
    level = levels[min(verbosity, 3)]

    logger = logging.getLogger("tele")
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Output to stderr ONLY - stdout is reserved for JSON Lines
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    return logger


def get_logger(name: str = "tele") -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (defaults to "tele")

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def get_log_level_name(verbosity: int) -> str:
    """Convert verbosity count to log level name.

    Args:
        verbosity: Number of -v flags (0-3)

    Returns:
        Log level name string
    """
    levels = ["WARNING", "INFO", "DEBUG", "TRACE"]
    return levels[min(verbosity, 3)]


def setup_processor_logging() -> logging.Logger:
    """Setup logging for processors based on TELE_LOG_LEVEL env var.

    Processors log to stderr only - stdout is reserved for JSON Lines output.

    Returns:
        Configured root logger
    """
    level_name = os.environ.get("TELE_LOG_LEVEL", "WARNING").upper()

    # Map level name to logging constant
    level_map = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "TRACE": TRACE,
    }
    level = level_map.get(level_name, logging.WARNING)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Output to stderr ONLY - stdout is reserved for JSON Lines
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    return logger