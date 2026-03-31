"""Source file consumer for reading messages from incoming files."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


def consume_from_offset(file_path: Path, byte_offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """Read complete JSON Lines messages from a file starting at byte offset.

    Uses seek() for efficient file positioning. Reads lines until end of file.
    Skips incomplete lines (lines without newline at end) as these may be
    mid-write by the data source.

    Args:
        file_path: Path to the JSONL file to read
        byte_offset: Byte position to start reading from

    Returns:
        Tuple of (messages, new_byte_offset):
            - messages: List of parsed JSON message dictionaries
            - new_byte_offset: Byte position after last complete line read
    """
    if not file_path.exists():
        logger.debug("File does not exist: %s", file_path)
        return [], 0

    messages: List[Dict[str, Any]] = []
    file_size = file_path.stat().st_size

    # If offset is at or beyond file size, nothing to read
    if byte_offset >= file_size:
        return [], byte_offset

    try:
        # Use binary mode for correct byte positioning
        with open(file_path, 'rb') as f:
            f.seek(byte_offset)
            content = f.read()

        if not content:
            return [], byte_offset

        # Process content line by line
        # Track the byte offset of complete lines
        current_offset = byte_offset

        # Split content by newlines, but track positions
        # We need to identify complete lines (ending with \n)
        lines_and_positions = []
        pos = 0
        while pos < len(content):
            newline_pos = content.find(b'\n', pos)
            if newline_pos == -1:
                # No newline found - this is a partial line
                break
            # Extract the line (without the newline)
            line_bytes = content[pos:newline_pos]
            lines_and_positions.append((line_bytes, newline_pos + 1))
            pos = newline_pos + 1

        # Process each complete line
        for line_bytes, end_pos in lines_and_positions:
            line_text = line_bytes.decode('utf-8')
            line_text = line_text.strip()

            if not line_text:
                # Empty line, just update offset
                current_offset = byte_offset + end_pos
                continue

            try:
                msg = json.loads(line_text)
                if isinstance(msg, dict):
                    messages.append(msg)
                    current_offset = byte_offset + end_pos
                else:
                    logger.warning("Skipping non-object JSON: %s", line_text[:100])
                    current_offset = byte_offset + end_pos
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse JSON at offset %d: %s", current_offset, e)
                current_offset = byte_offset + end_pos

        return messages, current_offset

    except Exception as e:
        logger.error("Error reading file %s: %s", file_path, e)
        return [], byte_offset


class SourceConsumer:
    """Consumes messages from a data source's incoming files.

    Manages reading from incoming files, handling file transitions,
    and updating state as messages are consumed.

    Attributes:
        source_name: Name of the data source
        state_manager: SourceStateManager instance for state persistence
    """

    def __init__(self, source_name: str, state_manager):
        """Initialize the consumer.

        Args:
            source_name: Identifier for the data source
            state_manager: SourceStateManager instance for state management
        """
        self.source_name = source_name
        self.state_manager = state_manager

    def consume_available(self) -> List[Dict[str, Any]]:
        """Consume all available messages from the source.

        Reads from the current file at the stored offset. When the current
        file is exhausted (offset == file_size), switches to the next file
        using state_manager.get_next_file().

        Returns:
            List of message dictionaries read from the source
        """
        all_messages: List[Dict[str, Any]] = []

        # Load current state
        state = self.state_manager.load(self.source_name)
        current_file = state.current_file
        byte_offset = state.byte_offset

        # If no current file, try to get the first one
        if not current_file:
            first_file = self.state_manager.get_next_file(self.source_name, "")
            if first_file is None:
                # No files available
                return []
            current_file = first_file.name
            byte_offset = 0

        # Read from current file, then subsequent files
        max_iterations = 100  # Safety limit
        iterations = 0

        while iterations < max_iterations:
            iterations += 1

            # Get the full path to current file
            source_dir = self.state_manager.get_source_dir(self.source_name)
            file_path = source_dir / current_file

            # Check if file exists
            if not file_path.exists():
                logger.warning("Current file does not exist: %s", file_path)
                # Try to get next file
                next_file = self.state_manager.get_next_file(self.source_name, current_file)
                if next_file is None:
                    break
                current_file = next_file.name
                byte_offset = 0
                continue

            # Get file size
            file_size = file_path.stat().st_size

            # Check if we've exhausted this file
            if byte_offset >= file_size:
                # Move to next file
                next_file = self.state_manager.get_next_file(self.source_name, current_file)
                if next_file is None:
                    # No more files, save state and return
                    self.state_manager.update_offset(
                        self.source_name, current_file, byte_offset
                    )
                    break
                current_file = next_file.name
                byte_offset = 0
                continue

            # Read messages from current file at offset
            messages, new_offset = consume_from_offset(file_path, byte_offset)

            if messages:
                all_messages.extend(messages)

            # Update state
            byte_offset = new_offset
            self.state_manager.update_offset(
                self.source_name, current_file, byte_offset
            )

            # Check if we've read all available content
            if new_offset < file_size:
                # There's still content (partial line at end), wait for more
                break

            # File exhausted, will loop to get next file

        return all_messages