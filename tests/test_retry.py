"""Tests for retry utility."""

import asyncio
import pytest

from tele.retry import retry_async


class TestRetryAsync:
    """Test retry_async function."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Should return immediately on success."""
        call_count = 0

        async def succeed():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_async(succeed)
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retry(self):
        """Should retry on matching exception."""
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return "success"

        result = await retry_async(
            fail_then_succeed,
            retry_exceptions=(ValueError,),
            base_delay=0.01,  # Fast for tests
        )
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Should raise after max retries exhausted."""
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent error")

        with pytest.raises(ValueError, match="permanent error"):
            await retry_async(
                always_fail,
                max_retries=2,
                retry_exceptions=(ValueError,),
                base_delay=0.01,
            )
        assert call_count == 3  # Initial + 2 retries

    @pytest.mark.asyncio
    async def test_no_retry_on_non_matching_exception(self):
        """Should not retry on non-matching exception."""
        call_count = 0

        async def raise_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            await retry_async(
                raise_type_error,
                retry_exceptions=(ValueError,),  # Different exception type
                base_delay=0.01,
            )
        assert call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_passes_arguments(self):
        """Should pass positional and keyword arguments."""
        async def echo(a, b, c=None):
            return (a, b, c)

        result = await retry_async(echo, 1, 2, c=3)
        assert result == (1, 2, 3)

    @pytest.mark.asyncio
    async def test_custom_max_retries(self):
        """Should respect custom max_retries."""
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await retry_async(
                always_fail,
                max_retries=5,
                retry_exceptions=(RuntimeError,),
                base_delay=0.01,
            )
        assert call_count == 6  # Initial + 5 retries