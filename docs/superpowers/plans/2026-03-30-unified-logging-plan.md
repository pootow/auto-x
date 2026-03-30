# Unified Logging System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a unified colored logging system with fixed-width prefix format for tele and processor output.

**Architecture:** Custom Formatter for tele internal logs (Python logging), plus processor output interception in executor (asyncio.subprocess stderr capture → level inference → reformat). Two independent modules handling各自的职责.

**Tech Stack:** Python logging, colorama for colors, asyncio.subprocess for processor interception

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tele/log.py` | ColoredFormatter, setup_logging, component mapping, level colors |
| `tele/executor.py` | Processor output interception, level inference, format and output |
| `tele/cli.py` | Import and use new log module, pass process name |
| `tests/test_log.py` | Tests for new formatter, colors, level inference |

---

### Task 1: ColoredFormatter Implementation

**Files:**
- Modify: `tele/log.py`
- Test: `tests/test_log.py`

- [ ] **Step 1: Write the failing test for format output**

```python
# tests/test_log.py - add to existing file

import logging
import os
from tele.log import ColoredFormatter, setup_logging, COMPONENT_MAP, get_component_logger


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

        # Should match format: [tele][12345][poll ][INFO ] YYYY-MM-DD HH:MM:SS | Connected to Telegram
        assert '[tele]' in result
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_log.py::TestColoredFormatter -v`
Expected: FAIL with "ColoredFormatter not defined" or similar

- [ ] **Step 3: Write ColoredFormatter implementation**

```python
# tele/log.py - replace entire file content

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
DATAFLOW = 15  # Was 3, now between DEBUG(10) and INFO(20)

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

# Component name mapping (logger name → 5-char component)
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
        Fore.LIGHT_BLUE_EX,
        Fore.LIGHT_GREEN_EX,
        Fore.LIGHT_CYAN_EX,
        Fore.LIGHT_MAGENTA_EX,
        Fore.LIGHT_YELLOW_EX,
        Fore.LIGHT_RED_EX,
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

    Format: [tele][12345][poll ][INFO ] YYYY-MM-DD HH:MM:SS | Message

    For DATAFLOW: [tele][12345][exec ][INFO ] YYYY-MM-DD HH:MM:SS | [flow ] Message
    """

    def __init__(self, process_name: str = 'tele', component: str = None):
        """Initialize formatter.

        Args:
            process_name: Process name (5 chars max)
            component: Component name (5 chars max), or None to infer from logger
        """
        super().__init__()
        self.process_name = process_name[:5].ljust(5)
        self.component = component
        self.pid = str(os.getpid())[:5].ljust(5)
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

        # Build prefix
        prefix = f'{self.process_color}[{self.process_name}][{self.pid}][{component}]{level_color}[{level_display}]'

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
    levels = [logging.WARNING, logging.INFO, logging.DEBUG, DATAFLOW]
    level = levels[min(verbosity, 3)]

    logger = logging.getLogger('tele')
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

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
    handler.setFormatter(ColoredFormatter(process_name=process_name))
    logger.addHandler(handler)

    return logger
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_log.py::TestColoredFormatter -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add tele/log.py tests/test_log.py
git commit -m "feat(log): add ColoredFormatter with fixed-width prefix format

- New format: [tele][pid][comp][LEVEL] timestamp | message
- DATAFLOW level shows INFO with [flow ] prefix in message
- TRACE merged into DEBUG
- Level colors: DEBUG gray, INFO bright, WARN yellow, ERROR red
- Process prefix color randomized per process"
```

---

### Task 2: Processor Output Interception

**Files:**
- Modify: `tele/executor.py`
- Test: `tests/test_executor.py` (create if needed)

- [ ] **Step 1: Write the failing test for processor output interception**

```python
# tests/test_executor.py - new file

import pytest
import asyncio
from tele.executor import run_exec_command, infer_level, format_processor_line


class TestInferLevel:
    """Tests for level inference from processor output."""

    def test_error_keywords(self):
        assert infer_level("Error: something failed") == "ERROR"
        assert infer_level("FAILED to process") == "ERROR"
        assert infer_level("Exception occurred") == "ERROR"

    def test_warn_keywords(self):
        assert infer_level("Warning: check this") == "WARN"
        assert infer_level("WARN: deprecated") == "WARN"

    def test_default_info(self):
        assert infer_level("Processing message") == "INFO"
        assert infer_level("Download complete") == "INFO"


class TestFormatProcessorLine:
    """Tests for formatting processor output lines."""

    def test_format_basic_line(self, monkeypatch):
        monkeypatch.setattr('os.getpid', lambda: 12345)

        # Simulate processor output interception
        result = format_processor_line("ytdlp", "Download started", "INFO")
        assert '[ytdlp]' in result
        assert '[INFO ]' in result
        assert 'Download started' in result

    def test_format_error_line(self, monkeypatch):
        monkeypatch.setattr('os.getpid', lambda: 12345)

        result = format_processor_line("ytdlp", "Error: download failed", "ERROR")
        assert '[ytdlp]' in result
        assert '[ERROR]' in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_executor.py -v`
Expected: FAIL with "infer_level not defined"

- [ ] **Step 3: Write level inference and format functions**

```python
# tele/executor.py - add these functions at the top after imports

"""Command execution utility for bot mode."""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

from .log import DATAFLOW, get_process_color

logger = logging.getLogger(__name__)

# Default timeout for processor execution (30 minutes)
DEFAULT_EXEC_TIMEOUT = 1800

# Level colors (same as log.py)
LEVEL_COLORS = {
    'DEBUG': Fore.WHITE + Style.DIM,
    'INFO ': Fore.WHITE + Style.BRIGHT,
    'WARN ': Fore.YELLOW,
    'ERROR': Fore.RED,
}


def infer_level(line: str) -> str:
    """Infer log level from processor output line content.

    Args:
        line: Output line from processor

    Returns:
        Level string: 'ERROR', 'WARN ', or 'INFO '
    """
    lower = line.lower()
    if 'error' in lower or 'failed' in lower or 'exception' in lower or 'fatal' in lower:
        return 'ERROR'
    if 'warn' in lower or 'warning' in lower:
        return 'WARN '
    return 'INFO '


def format_processor_line(process_name: str, line: str, level: str = None) -> str:
    """Format a processor output line with tele logging format.

    Args:
        process_name: Processor command name (e.g., 'ytdlp', 'python')
        line: Output line content
        level: Level string, or None to infer from content

    Returns:
        Formatted line with prefix and colors
    """
    if level is None:
        level = infer_level(line)

    # Process name (5 chars)
    proc = process_name[:5].ljust(5)
    pid = str(os.getpid())[:5].ljust(5)

    # Component for processor output
    component = 'proc '.ljust(5)

    # Timestamp
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Colors
    proc_color = get_process_color(process_name)
    level_color = LEVEL_COLORS.get(level, Fore.WHITE)

    # Format
    return f'{proc_color}[{proc}][{pid}][{component}]{level_color}[{level}] {timestamp} | {line}'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_executor.py::TestInferLevel tests/test_executor.py::TestFormatProcessorLine -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tele/executor.py tests/test_executor.py
git commit -m "feat(executor): add processor output level inference and formatting

- infer_level(): keyword-based level inference (error/failed → ERROR)
- format_processor_line(): format processor output with tele logging style"
```

---

### Task 3: Integrate Interception into run_exec_command

**Files:**
- Modify: `tele/executor.py`

- [ ] **Step 1: Write test for stderr interception**

```python
# tests/test_executor.py - add to existing file

import pytest
import asyncio
from tele.executor import run_exec_command


class TestRunExecCommandStderr:
    """Tests for stderr interception in run_exec_command."""

    @pytest.mark.asyncio
    async def test_stderr_is_intercepted_and_formatted(self):
        """Test that processor stderr output is intercepted and formatted."""
        # Use a command that outputs to stderr
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Use echo to stderr (works on Windows with Python)
        # Python -c "import sys; sys.stderr.write('test output\\n')"
        cmd = 'python -c "import sys; print(\'test stderr\', file=sys.stderr)"'

        results = await run_exec_command(cmd, messages, shell=True)

        # Should return empty result since no stdout JSON
        assert len(results) == 1
        assert results[0]['status'] == 'error'

    @pytest.mark.asyncio
    async def test_stdout_json_still_parsed(self):
        """Test that stdout JSON Lines are still parsed correctly."""
        messages = [{"id": 1, "chat_id": 123, "text": "test"}]

        # Command that outputs valid JSON to stdout
        cmd = 'python -c "print(\'{"id": 1, "chat_id": 123, "status": "success"}\\n\')"'

        results = await run_exec_command(cmd, messages, shell=True)

        assert len(results) == 1
        assert results[0]['status'] == 'success'
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `uv run pytest tests/test_executor.py::TestRunExecCommandStderr -v`
Expected: Tests pass but stderr not formatted yet (just checking baseline)

- [ ] **Step 3: Modify run_exec_command to intercept stderr**

```python
# tele/executor.py - modify run_exec_command function

async def run_exec_command(
    command: str,
    messages: List[Dict[str, Any]],
    shell: bool = False,
    timeout: Optional[float] = DEFAULT_EXEC_TIMEOUT,
) -> List[Dict[str, Any]]:
    """Run external command with messages as stdin, parse stdout for results.

    This function NEVER raises exceptions - it returns error status for all
    messages on failure. This ensures the daemon never crashes due to
    processor failures.

    Args:
        command: Command to execute
        messages: List of message dicts to send as JSON Lines
        shell: Use shell execution
        timeout: Timeout in seconds (default: 30 minutes)

    Returns:
        List of message dicts from stdout (with status field).
        On any failure, returns error status for all input messages.
    """
    if not messages:
        return []

    # Prepare stdin as JSON Lines
    stdin_data = "\n".join(json.dumps(msg) for msg in messages)
    logger.debug("Running command: %s with %s messages (timeout=%ss)", command, len(messages), timeout)

    # Log dataflow to processor
    for msg in messages:
        logger.log(DATAFLOW, ">>> %s", json.dumps(msg))

    # Extract process name from command (first word)
    process_name = command.split()[0] if command else 'proc'
    # Handle path-like commands (e.g., 'python', 'ytdlp')
    if '/' in process_name or '\\' in process_name:
        process_name = process_name.split('/')[-1].split('\\')[-1]
    process_name = process_name[:5]

    proc = None
    try:
        # Execute command - capture BOTH stdout and stderr
        if shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *command.split(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        # Wait for completion with timeout
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_data.encode()),
            timeout=timeout
        )

        # Process stderr output - format each line
        if stderr:
            stderr_text = stderr.decode()
            for line in stderr_text.strip().split('\n'):
                if line:
                    formatted = format_processor_line(process_name, line)
                    print(formatted, file=sys.stderr)

        if proc.returncode != 0:
            logger.error("Command failed with exit code %s", proc.returncode)
            return [
                {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
                for m in messages if m.get("id") and m.get("chat_id")
            ]

        # Parse stdout as JSON Lines
        results = []
        for line in stdout.decode().strip().split("\n"):
            if line:
                logger.log(DATAFLOW, "<<< %s", line)
                try:
                    result = json.loads(line)
                    if 'id' in result and 'chat_id' in result:
                        if 'status' not in result:
                            result['status'] = 'error'
                        results.append(result)
                        logger.debug("Parsed result: id=%s status=%s", result.get('id'), result.get('status'))
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid JSON line: %s...", line[:50])

        logger.debug("Command returned %s results", len(results))
        return results

    except asyncio.TimeoutError:
        logger.error("Processor timed out after %ss", timeout)
        if proc and proc.returncode is None:
            try:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Process did not terminate after kill()")
            except Exception:
                pass
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]

    except FileNotFoundError:
        logger.error("Command not found: %s", command.split()[0] if command else "")
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]

    except PermissionError as e:
        logger.error("Permission denied executing command: %s", e)
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]

    except Exception as e:
        logger.error("Unexpected error executing command: %s", e, exc_info=True)
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_executor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tele/executor.py tests/test_executor.py
git commit -m "feat(executor): intercept and format processor stderr output

- stderr now captured and formatted line by line
- each line gets level inference and tele logging format
- stdout JSON Lines parsing unchanged"
```

---

### Task 4: Update CLI and Integration

**Files:**
- Modify: `tele/cli.py`

- [ ] **Step 1: Verify current imports work**

Run: `uv run pytest tests/test_cli.py -v` (if exists) or `uv run python -c "from tele.cli import cli"`
Expected: No import errors

- [ ] **Step 2: Update CLI imports to use new log module**

```python
# tele/cli.py - update imports (line ~20)

# Replace:
from .log import setup_logging, get_logger, get_log_level_name, DATAFLOW

# With (same imports, but new module provides ColoredFormatter):
from .log import setup_logging, get_logger, get_log_level_name, DATAFLOW, ColoredFormatter
```

No other changes needed - setup_logging now uses ColoredFormatter internally.

- [ ] **Step 3: Test CLI still works**

Run: `uv run python -c "from tele.cli import cli; print('OK')"`
Expected: "OK"

- [ ] **Step 4: Commit**

```bash
git add tele/cli.py
git commit -m "refactor(cli): import ColoredFormatter from new log module"
```

---

### Task 5: Update Existing Tests

**Files:**
- Modify: `tests/test_log.py`

- [ ] **Step 1: Update existing tests for new log levels**

```python
# tests/test_log.py - update existing tests

# Remove TRACE tests, update DATAFLOW tests

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


class TestDataflowLevel:
    """Tests for DATAFLOW log level."""

    def test_dataflow_is_between_debug_and_info(self):
        assert logging.DEBUG < DATAFLOW < logging.INFO

    def test_dataflow_value_is_15(self):
        assert DATAFLOW == 15

    def test_dataflow_level_name_registered(self):
        assert logging.getLevelName(DATAFLOW) == "DATAFLOW"
```

- [ ] **Step 2: Remove old TRACE tests**

Delete the `TestTraceLevel` class entirely from `tests/test_log.py`.

- [ ] **Step 3: Run all log tests**

Run: `uv run pytest tests/test_log.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_log.py
git commit -m "test(log): update tests for new logging system

- TRACE removed (merged into DEBUG)
- DATAFLOW now level 15 (between DEBUG and INFO)
- verbosity capped at 3"
```

---

### Task 6: Update Other Modules Using Log

**Files:**
- Modify: `tele/bot_client.py`, `tele/async_queue.py`, `tele/state.py`, `tele/retry.py`

- [ ] **Step 1: Check modules using DATAFLOW constant**

Run: `grep -l "DATAFLOW" tele/*.py`
Expected: `tele/cli.py`, `tele/executor.py` (already updated)

- [ ] **Step 2: Check modules using log imports**

Run: `grep -l "from .log import" tele/*.py`
Expected: Only `tele/cli.py` and `tele/executor.py` import from log module

Other modules use `logging.getLogger(__name__)` which is standard - they automatically inherit the tele logger's configuration through propagation.

- [ ] **Step 3: Verify propagation works**

```python
# Quick test that child loggers inherit formatter
import logging
from tele.log import setup_logging, COMPONENT_MAP

setup_logging(2)  # DEBUG level

# Test child logger
child = logging.getLogger('tele.bot')
assert child.propagate == True
print('OK')
```

Run: `uv run python -c "import logging; from tele.log import setup_logging, COMPONENT_MAP; setup_logging(2); child = logging.getLogger('tele.bot'); assert child.propagate; print('OK')"`
Expected: "OK"

- [ ] **Step 4: No changes needed - commit documentation**

```bash
git add tele/*.py
git commit -m "docs: log propagation confirmed for child loggers

- tele.bot, tele.executor, etc. inherit from tele logger
- COMPONENT_MAP provides component name mapping"
```

---

### Task 7: Final Integration Test

**Files:**
- Test: Manual integration test

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Manual test - run tele with verbose logging**

Run: `uv run tele --bot --chat test --exec "echo" -vvv`
(Expected to fail without proper config, but check log format)

- [ ] **Step 3: Verify log format visually**

Check that output matches expected format:
```
[tele][12345][poll ][INFO ] 2025-03-30 14:30:05 | Bot mode started
```

- [ ] **Step 4: Final commit if all tests pass**

```bash
git add -A
git commit -m "feat: unified colored logging system complete

- Format: [proc][pid][comp][LEVEL] timestamp | message
- Process prefix: random color per process
- Level colors: DEBUG gray, INFO bright, WARN yellow, ERROR red
- DATAFLOW shows INFO with [flow ] prefix
- Processor stderr intercepted and formatted
- TRACE merged into DEBUG"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | ColoredFormatter + new log levels | `tele/log.py`, `tests/test_log.py` |
| 2 | Level inference functions | `tele/executor.py`, `tests/test_executor.py` |
| 3 | stderr interception in run_exec_command | `tele/executor.py` |
| 4 | CLI imports | `tele/cli.py` |
| 5 | Update existing tests | `tests/test_log.py` |
| 6 | Verify child logger propagation | No changes needed |
| 7 | Final integration test | Manual verification |