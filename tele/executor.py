"""Command execution utility for bot mode."""

import asyncio
import json
import logging
from typing import List, Dict, Any

from .log import DATAFLOW

logger = logging.getLogger(__name__)


async def run_exec_command(
    command: str,
    messages: List[Dict[str, Any]],
    shell: bool = False
) -> List[Dict[str, Any]]:
    """Run external command with messages as stdin, parse stdout for results.

    Args:
        command: Command to execute
        messages: List of message dicts to send as JSON Lines
        shell: Use shell execution

    Returns:
        List of message dicts from stdout (with status field)

    Raises:
        RuntimeError: If command fails
    """
    # Prepare stdin as JSON Lines
    stdin_data = "\n".join(json.dumps(msg) for msg in messages)
    logger.debug("Running command: %s with %s messages", command, len(messages))

    # Log dataflow to processor
    for msg in messages:
        logger.log(DATAFLOW, ">>> %s", json.dumps(msg))

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

    stdout, _ = await proc.communicate(stdin_data.encode())

    if proc.returncode != 0:
        logger.error("Command failed with exit code %s", proc.returncode)
        raise RuntimeError(f"Command failed with exit code {proc.returncode}")

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