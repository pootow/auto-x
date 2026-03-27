"""Command execution utility for bot mode."""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional

from .log import DATAFLOW

logger = logging.getLogger(__name__)

# Default timeout for processor execution (30 minutes)
DEFAULT_EXEC_TIMEOUT = 1800


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
                await proc.wait()
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