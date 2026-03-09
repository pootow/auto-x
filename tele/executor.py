"""Command execution utility for bot mode."""

import asyncio
import json
from typing import List, Dict, Any


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

    # Execute command
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

    stdout, stderr = await proc.communicate(stdin_data.encode())

    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {stderr.decode()}")

    # Parse stdout as JSON Lines
    results = []
    for line in stdout.decode().strip().split("\n"):
        if line:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # Skip invalid lines

    return results