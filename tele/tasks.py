"""Task definitions for bot daemon.

This module defines the task types used in the bot daemon's queue system:
- MessageTask: Messages to be processed by exec command
- InteractionTask: Interactions to be sent to Telegram (reactions, replies)

Each task type is a dataclass that can be serialized to/from JSON.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from .async_queue import QueueItem


@dataclass
class MessageTask(QueueItem):
    """Message to be processed by exec command.

    Attributes:
        id: Message ID (unique identifier)
        chat_id: Chat ID where the message was sent
        update_id: Telegram update ID (for offset tracking)
        message: Formatted message data (dict with id, text, sender_id, date, etc.)
        exec_cmd: Command to execute for processing
        retry_count: Number of retry attempts
        created_at: When the task was created
        last_attempt: When the last processing attempt was made
    """
    chat_id: int = 0
    update_id: int = 0
    message: Dict[str, Any] = field(default_factory=dict)
    exec_cmd: str = ""
    retry_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    last_attempt: Optional[str] = None


@dataclass
class InteractionTask(QueueItem):
    """Interaction to be sent to Telegram.

    Interaction types:
    - 'received_mark': Reaction when message is received
    - 'result_mark': Reaction based on processing result (success/fail)
    - 'reply_video': Send a video reply
    - 'reply_photo': Send a photo reply
    - 'reply_text': Send a text reply

    Attributes:
        id: Message ID (for reply_to and tracking)
        chat_id: Chat ID where to send the interaction
        interaction_type: Type of interaction (see above)
        data: Type-specific data (emoji for reactions, media for replies)
        retry_count: Number of retry attempts
        created_at: When the task was created
        last_attempt: When the last attempt was made
    """
    chat_id: int = 0
    interaction_type: str = ""  # 'received_mark', 'result_mark', 'reply_video', 'reply_photo', 'reply_text'
    data: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    last_attempt: Optional[str] = None


# Dead-letter variants (for manual recovery)

@dataclass
class DeadMessageTask(MessageTask):
    """Message that exceeded retries.

    Additional attributes:
        error: Error message describing the failure
        failed_at: When the message was moved to dead-letter
    """
    error: str = ""
    failed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))


@dataclass
class DeadInteractionTask(InteractionTask):
    """Interaction that exceeded retries.

    Additional attributes:
        error: Error message describing the failure
        failed_at: When the interaction was moved to dead-letter
    """
    error: str = ""
    failed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))


# Helper functions for creating tasks

def create_message_task(
    message_id: int,
    chat_id: int,
    update_id: int,
    message: Dict[str, Any],
    exec_cmd: str,
) -> MessageTask:
    """Create a new MessageTask.

    Args:
        message_id: Telegram message ID
        chat_id: Chat ID
        update_id: Telegram update ID
        message: Formatted message data
        exec_cmd: Command to execute

    Returns:
        A new MessageTask instance
    """
    return MessageTask(
        id=message_id,
        chat_id=chat_id,
        update_id=update_id,
        message=message,
        exec_cmd=exec_cmd,
    )


def create_received_mark_task(
    message_id: int,
    chat_id: int,
    emoji: str,
) -> InteractionTask:
    """Create a received_mark interaction task.

    Args:
        message_id: Message ID to react to
        chat_id: Chat ID
        emoji: Emoji to use for the reaction

    Returns:
        A new InteractionTask for received_mark
    """
    return InteractionTask(
        id=message_id,
        chat_id=chat_id,
        interaction_type='received_mark',
        data={'emoji': emoji},
    )


def create_result_mark_task(
    message_id: int,
    chat_id: int,
    emoji: str,
) -> InteractionTask:
    """Create a result_mark interaction task.

    Args:
        message_id: Message ID to react to
        chat_id: Chat ID
        emoji: Emoji to use for the reaction (success or failure)

    Returns:
        A new InteractionTask for result_mark
    """
    return InteractionTask(
        id=message_id,
        chat_id=chat_id,
        interaction_type='result_mark',
        data={'emoji': emoji},
    )


def create_reply_task(
    message_id: int,
    chat_id: int,
    reply_item: Dict[str, Any],
) -> InteractionTask:
    """Create a reply interaction task.

    Args:
        message_id: Message ID to reply to
        chat_id: Chat ID
        reply_item: Reply data with 'text' and optional 'media'

    Returns:
        A new InteractionTask for the reply
    """
    media = reply_item.get('media')
    if media:
        media_type = media.get('type', 'text')
        # Map 'image' to 'photo' for consistency with Telegram Bot API terminology
        if media_type == 'image':
            media_type = 'photo'
        interaction_type = f'reply_{media_type}'  # 'reply_video' or 'reply_photo'
    else:
        interaction_type = 'reply_text'

    return InteractionTask(
        id=message_id,
        chat_id=chat_id,
        interaction_type=interaction_type,
        data={
            'text': reply_item.get('text', ''),
            'media': media,
        },
    )