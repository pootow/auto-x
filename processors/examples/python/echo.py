#!/usr/bin/env python3
"""
Echo processor - demonstrates the basic processor contract.

Reads JSON Lines from stdin, writes results to stdout.
Each output must include id, chat_id, and status.
"""

import json
import logging
import sys
import os

# Add tele module to path for importing log utilities
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tele.log import setup_processor_logging

# Setup logging based on TELE_LOG_LEVEL env var
setup_processor_logging()

logger = logging.getLogger(__name__)


def process_message(msg: dict) -> dict:
    """Process a single message and return the result."""
    # Extract required fields
    msg_id = msg.get("id")
    chat_id = msg.get("chat_id")

    # Validate required fields exist
    if msg_id is None or chat_id is None:
        # Cannot process without id/chat_id - return failure
        return {
            "id": msg_id or 0,
            "chat_id": chat_id or 0,
            "status": "failed"
        }

    # Example: log the message text (for debugging)
    text = msg.get("text")
    if text:
        # Log to stderr so it doesn't interfere with stdout
        logger.debug("Processing message %s: %s...", msg_id, text[:50])

    # Your processing logic goes here
    # This example just marks everything as success
    return {
        "id": msg_id,
        "chat_id": chat_id,
        "status": "success"
    }


def main():
    """Read JSON Lines from stdin, process each, output results."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
            result = process_message(msg)
            print(json.dumps(result))
        except json.JSONDecodeError as e:
            # Log error to stderr, output failure
            logger.error("Invalid JSON: %s", e)
            print(json.dumps({"id": 0, "chat_id": 0, "status": "failed"}))


if __name__ == "__main__":
    main()