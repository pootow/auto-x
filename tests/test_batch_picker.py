import pytest
from datetime import datetime, timezone, timedelta
from tele.batch_picker import BatchPicker
from tele.state import PendingMessage


class TestBatchPicker:
    """Tests for pull-based debounce batch picker."""

    def test_batch_picker_initialization(self):
        """BatchPicker should initialize with given parameters."""
        picker = BatchPicker(page_size=10, debounce_interval=3.0)
        assert picker.page_size == 10
        assert picker.debounce_interval == 3.0

    def test_batch_picker_defaults(self):
        """BatchPicker should have sensible defaults."""
        picker = BatchPicker()
        assert picker.page_size == 10
        assert picker.debounce_interval == 3.0