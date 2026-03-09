"""Tests for message batching utility."""

import asyncio

import pytest

from tele.batcher import MessageBatcher


class TestMessageBatcher:
    """Test cases for MessageBatcher."""

    @pytest.mark.asyncio
    async def test_batcher_accumulates_messages(self):
        """MessageBatcher should accumulate messages until page_size."""
        batcher = MessageBatcher(page_size=3, interval=10.0)
        results = []

        async def on_batch(messages):
            results.append(messages)

        batcher.on_batch = on_batch

        await batcher.add({"id": 1})
        await batcher.add({"id": 2})
        assert len(results) == 0  # Not yet

        await batcher.add({"id": 3})
        await asyncio.sleep(0.1)  # Let callback execute

        assert len(results) == 1
        assert len(results[0]) == 3

    @pytest.mark.asyncio
    async def test_batcher_flushes_on_interval(self):
        """MessageBatcher should flush after interval of silence."""
        batcher = MessageBatcher(page_size=100, interval=0.1)
        results = []

        async def on_batch(messages):
            results.append(messages)

        batcher.on_batch = on_batch

        await batcher.add({"id": 1})
        assert len(results) == 0

        await asyncio.sleep(0.2)  # Wait for debounce

        assert len(results) == 1
        assert len(results[0]) == 1

    @pytest.mark.asyncio
    async def test_batcher_flush_remaining(self):
        """MessageBatcher should flush remaining messages on shutdown."""
        batcher = MessageBatcher(page_size=100, interval=10.0)
        results = []

        async def on_batch(messages):
            results.append(messages)

        batcher.on_batch = on_batch

        await batcher.add({"id": 1})
        await batcher.add({"id": 2})
        assert len(results) == 0

        await batcher.flush_remaining()

        assert len(results) == 1
        assert len(results[0]) == 2