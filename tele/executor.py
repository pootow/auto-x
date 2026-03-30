"""Command execution utility for bot mode."""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from colorama import Fore, Style, init

from .log import DATAFLOW, get_process_color

# Initialize colorama
init(autoreset=True)

logger = logging.getLogger(__name__)

# Default timeout for processor execution (30 minutes)
DEFAULT_EXEC_TIMEOUT = 1800

# Level colors for processor output (string keys matching display names)
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

    proc = None
    try:
        # Execute command (stderr inherits for real-time processor logs)
        if shell:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *command.split(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )

        # Wait for completion with timeout
        stdout, _ = await asyncio.wait_for(
            proc.communicate(stdin_data.encode()),
            timeout=timeout
        )

        if proc.returncode != 0:
            logger.error("Command failed with exit code %s", proc.returncode)
            # Return error status for all messages - they will be retried
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
                    # Must have id and chat_id at minimum
                    if 'id' in result and 'chat_id' in result:
                        # Default to error (retriable) if no status
                        if 'status' not in result:
                            result['status'] = 'error'
                        results.append(result)
                        logger.debug("Parsed result: id=%s status=%s", result.get('id'), result.get('status'))
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid JSON line: %s...", line[:50])
                    pass  # Skip invalid lines

        logger.debug("Command returned %s results", len(results))
        return results

    except asyncio.TimeoutError:
        logger.error("Processor timed out after %ss", timeout)
        # Kill the process if it's still running
        if proc and proc.returncode is None:
            try:
                proc.kill()
                # On Windows, kill() may not terminate child processes
                # Use wait() with timeout to avoid hanging indefinitely
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    # Process didn't terminate, log and continue
                    logger.warning("Process did not terminate after kill()")
            except Exception:
                pass
        # Return error status for all messages - they will be retried
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]

    except FileNotFoundError:
        logger.error("Command not found: %s", command.split()[0] if command else "")
        # Return error status for all messages - command might be installed later
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]

    except PermissionError as e:
        logger.error("Permission denied executing command: %s", e)
        # Return error status - might be a transient issue
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]

    except Exception as e:
        logger.error("Unexpected error executing command: %s", e, exc_info=True)
        # Return error status for all messages
        return [
            {"id": m.get("id"), "chat_id": m.get("chat_id"), "status": "error"}
            for m in messages if m.get("id") and m.get("chat_id")
        ]