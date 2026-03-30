"""Logging utilities for tele and processors."""

import logging
import os
import sys
import random
from datetime import datetime, timezone
from colorama import Fore, Style, init

# Initialize colorama for Windows support
init(autoreset=True)

# DATAFLOW level (between DEBUG and INFO) - shows raw JSON in pipeline
# DEBUG level (-vv) shows DATAFLOW messages because 15 >= 10
# INFO level (-v) filters out DATAFLOW because 15 < 20
DATAFLOW = 15

# TRACE removed - merged into DEBUG

logging.addLevelName(DATAFLOW, "DATAFLOW")

# Level colors
LEVEL_COLORS = {
    logging.DEBUG: Fore.WHITE + Style.DIM,
    logging.INFO: Fore.WHITE + Style.BRIGHT,
    logging.WARNING: Fore.YELLOW,
    logging.ERROR: Fore.RED,
    DATAFLOW: Fore.WHITE + Style.BRIGHT,  # DATAFLOW displays as INFO color
}

# Level display names (5 chars)
LEVEL_DISPLAY = {
    logging.DEBUG: 'DEBUG',
    logging.INFO: 'INFO ',
    logging.WARNING: 'WARN ',
    logging.ERROR: 'ERROR',
    DATAFLOW: 'INFO ',  # DATAFLOW shows as INFO level
}

# Component name mapping (logger name -> 5-char component)
COMPONENT_MAP = {
    'tele.bot': 'poll',
    'tele.executor': 'exec',
    'tele.bot_client': 'api',
    'tele.async_queue': 'queue',
    'tele.state': 'state',
    'tele.retry': 'retry',
}

# Process prefix colors - generated randomly at startup
PROCESS_COLORS = {}
USED_COLORS = []

def get_process_color(process_name: str) -> str:
    """Get or generate a random color for a process prefix.

    Args:
        process_name: Process name (e.g., 'tele', 'ytdlp')

    Returns:
        Colorama color code
    """
    if process_name in PROCESS_COLORS:
        return PROCESS_COLORS[process_name]

    # Available bright colors for process prefixes
    available_colors = [
        Fore.BLUE,
        Fore.GREEN,
        Fore.CYAN,
        Fore.MAGENTA,
        Fore.LIGHTBLUE_EX,
        Fore.LIGHTGREEN_EX,
        Fore.LIGHTCYAN_EX,
        Fore.LIGHTMAGENTA_EX,
        Fore.LIGHTYELLOW_EX,
        Fore.LIGHTRED_EX,
    ]

    # Filter out already used colors
    unused = [c for c in available_colors if c not in USED_COLORS]

    if unused:
        color = random.choice(unused)
    else:
        # All colors used, just pick any
        color = random.choice(available_colors)

    USED_COLORS.append(color)
    PROCESS_COLORS[process_name] = color
    return color


class ColoredFormatter(logging.Formatter):
    """Formatter with fixed-width prefix and level-based colors.

    Format (with PID): [tele][12345][poll ][INFO ] YYYY-MM-DD HH:MM:SS | Message
    Format (without PID): [tele][poll ][INFO ] YYYY-MM-DD HH:MM:SS | Message

    For DATAFLOW: [tele][poll ][INFO ] YYYY-MM-DD HH:MM:SS | [flow ] Message
    """

    def __init__(self, process_name: str = 'tele', component: str = None, show_pid: bool = False):
        """Initialize formatter.

        Args:
            process_name: Process name (5 chars max)
            component: Component name (5 chars max), or None to infer from logger
            show_pid: Whether to show PID in output (default: False)
        """
        super().__init__()
        self.process_name = process_name[:5].ljust(5)
        self.component = component
        self.pid = str(os.getpid())[:5].ljust(5)
        self.show_pid = show_pid
        self.process_color = get_process_color(process_name)

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record.

        Args:
            record: Log record to format

        Returns:
            Formatted string with colors
        """
        # Get component name
        if self.component:
            component = self.component[:5].ljust(5)
        else:
            # Infer from logger name
            component = COMPONENT_MAP.get(record.name, record.name.split('.')[-1])[:5].ljust(5)

        # Get level display
        level = record.levelno
        level_display = LEVEL_DISPLAY.get(level, 'INFO ')
        level_color = LEVEL_COLORS.get(level, Fore.WHITE)

        # Timestamp (local time, no timezone)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build prefix (with or without PID)
        if self.show_pid:
            prefix = f'{self.process_color}[{self.process_name}][{self.pid}][{component}]{level_color}[{level_display}]'
        else:
            prefix = f'{self.process_color}[{self.process_name}][{component}]{level_color}[{level_display}]'

        # Message
        msg = record.getMessage()

        # DATAFLOW special handling: add [flow ] prefix to message
        if level == DATAFLOW:
            msg = f'[flow ] {msg}'

        # Combine
        return f'{prefix} {timestamp} | {msg}'


def setup_logging(verbosity: int = 0) -> logging.Logger:
    """Setup logging based on verbosity level.

    Args:
        verbosity: Number of -v flags (0-3)
            0: WARNING
            1: INFO
            2: DEBUG (includes TRACE)
            3: DATAFLOW (includes all JSON flow)

    Returns:
        Configured logger for tele
    """
    levels = [logging.WARNING, logging.INFO, logging.DEBUG, logging.DEBUG]
    level = levels[min(verbosity, 3)]

    logger = logging.getLogger('tele')
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Prevent propagation to root logger (avoids duplicate output)
    logger.propagate = False

    # Set handler with ColoredFormatter
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(ColoredFormatter(process_name='tele'))
    logger.addHandler(handler)

    # Propagate to child loggers
    for name in COMPONENT_MAP.keys():
        child = logging.getLogger(name)
        child.setLevel(level)
        child.handlers.clear()
        child.propagate = True  # Use parent handler

    return logger


def get_logger(name: str = 'tele') -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (defaults to 'tele')

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
    levels = ['WARNING', 'INFO', 'DEBUG', 'DATAFLOW']
    return levels[min(verbosity, 3)]


def setup_processor_logging() -> logging.Logger:
    """Setup logging for processors based on TELE_LOG_LEVEL env var.

    Processors log to stderr only - stdout is reserved for JSON Lines output.

    Returns:
        Configured root logger
    """
    level_name = os.environ.get('TELE_LOG_LEVEL', 'WARNING').upper()

    level_map = {
        'CRITICAL': logging.CRITICAL,
        'ERROR': logging.ERROR,
        'WARNING': logging.WARNING,
        'INFO': logging.INFO,
        'DEBUG': logging.DEBUG,
        'DATAFLOW': DATAFLOW,
    }
    level = level_map.get(level_name, logging.WARNING)

    logger = logging.getLogger()
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Process name from env or default
    process_name = os.environ.get('TELE_PROCESS_NAME', 'proc')[:5].ljust(5)

    # Output to stderr ONLY
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(ColoredFormatter(process_name=process_name, show_pid=True))
    logger.addHandler(handler)

    return logger