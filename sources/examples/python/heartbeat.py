#!/usr/bin/env python3
"""
Heartbeat source - demonstrates the source protocol.

Generates heartbeat messages to incoming.{date}.jsonl.
Shows: scheduling, date-based file naming, append-only writing.

CORE CONVENTIONS (follow these when developing your own sources):
1. File naming: incoming.YYYY-MM-DD.jsonl (day-level, not seconds)
2. Date monotonicity: Always write to today's file (recalculate date each time)
3. Append-only: Only append, never modify or delete existing content
4. Atomic writes: Optional but recommended (temp file + rename)

Environment variables:
    TELE_SOURCE_PATH - Directory for incoming files (default: ~/.tele/state/sources/heartbeat)
    TELE_CHAT_ID     - Target chat ID for messages (default: 0)
    TELE_INTERVAL    - Seconds between heartbeats (default: 60)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Setup logging to stderr (stdout reserved for JSONL output to tele)
logging.basicConfig(
    stream=sys.stderr,
    format="[%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_source_path() -> Path:
    """Get the source directory path from environment."""
    path = os.environ.get("TELE_SOURCE_PATH", "~/.tele/state/sources/heartbeat")
    return Path(path).expanduser()


def get_incoming_file(base_path: Path) -> Path:
    """
    Get current day's incoming file path.

    CORE CONVENTION #1: File naming format is incoming.YYYY-MM-DD.jsonl
    CORE CONVENTION #2: Date must always increase - recalculate every call
    """
    # Recalculate date each time (handles midnight transition)
    date = datetime.now().strftime("%Y-%m-%d")
    return base_path / f"incoming.{date}.jsonl"


def generate_heartbeat(chat_id: int, source_name: str) -> dict:
    """Generate a heartbeat message with unique ID and timestamp."""
    now = datetime.now()
    return {
        "id": f"heartbeat-{uuid4()}",       # Unique ID for this heartbeat
        "chat_id": chat_id,                  # Target chat for notifications
        "text": f"Heartbeat at {now.isoformat()}",  # Message content
        "date": now.isoformat(),             # When this message was generated
        "source": source_name                # Source identification
    }


def write_message(base_path: Path, msg: dict) -> Path:
    """
    Append a message to the incoming file.

    CORE CONVENTION #3: Append-only - use "a" mode, never "w"
    CORE CONVENTION #4: Atomic writes (temp file + rename) - optional
    """
    # Ensure directory exists
    base_path.mkdir(parents=True, exist_ok=True)

    # Get current day's file (recalculates date)
    file_path = get_incoming_file(base_path)

    # Append mode - NEVER use overwrite mode ("w")
    # This ensures files are audit logs, not overwritten
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    return file_path


def main():
    """Run heartbeat loop, generating messages at configured interval."""
    # Configuration from environment
    base_path = get_source_path()
    chat_id = int(os.environ.get("TELE_CHAT_ID", "0"))
    interval = int(os.environ.get("TELE_INTERVAL", "60"))
    source_name = "heartbeat"

    logger.info("Starting heartbeat source")
    logger.info("Path: %s", base_path)
    logger.info("Chat ID: %s", chat_id)
    logger.info("Interval: %s seconds", interval)

    try:
        while True:
            # Generate heartbeat message
            msg = generate_heartbeat(chat_id, source_name)

            # Write to incoming file (date recalculated each iteration)
            file_path = write_message(base_path, msg)

            logger.info("Wrote heartbeat to %s", file_path.name)

            # Wait for next iteration
            # Note: Date will be recalculated after sleep, handling midnight
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.error("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()