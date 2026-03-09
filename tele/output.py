"""Output formatting for messages."""

import json
from datetime import datetime
from typing import Any, Optional


def format_message(message: Any, chat_id: Optional[int] = None, status: str = "pending") -> str:
    """Format a message as a JSON line.

    Args:
        message: Telethon Message object
        chat_id: Optional chat ID to include
        status: Processing status (pending, success, failed)

    Returns:
        JSON line string
    """
    data = {
        'id': message.id,
        'text': message.text or '',
        'sender_id': message.sender_id,
        'date': message.date.isoformat() if message.date else None,
        'chat_id': chat_id or (message.chat_id if hasattr(message, 'chat_id') else None),
        'status': status,
    }

    # Add optional fields
    if message.forward:
        data['is_forwarded'] = True
        if message.forward.from_id:
            data['forward_from_id'] = message.forward.from_id

    if message.media:
        data['has_media'] = True
        data['media_type'] = type(message.media).__name__

    if message.reactions:
        data['reactions'] = [
            {'emoji': r.reaction.emoticon, 'count': r.count}
            for r in message.reactions.results
        ]

    return json.dumps(data, ensure_ascii=False)


def format_messages(messages: list, chat_id: Optional[int] = None) -> str:
    """Format multiple messages as JSON lines.

    Args:
        messages: List of Telethon Message objects
        chat_id: Optional chat ID to include

    Returns:
        JSON lines string
    """
    lines = [format_message(msg, chat_id) for msg in messages]
    return '\n'.join(lines)


def parse_message_id(line: str) -> tuple[int, int]:
    """Parse a message ID and chat ID from a JSON line.

    Args:
        line: JSON line string

    Returns:
        Tuple of (message_id, chat_id)
    """
    data = json.loads(line)
    return data['id'], data['chat_id']


def format_output(data: Any, format_type: str = 'json') -> str:
    """Format data for output.

    Args:
        data: Data to format
        format_type: Output format ('json' or 'jsonl')

    Returns:
        Formatted string
    """
    if format_type == 'jsonl':
        if isinstance(data, list):
            return '\n'.join(json.dumps(item, ensure_ascii=False) for item in data)
        return json.dumps(data, ensure_ascii=False)

    # Default JSON format
    return json.dumps(data, ensure_ascii=False, indent=2)