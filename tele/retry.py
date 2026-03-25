"""Retry utility for transient failures."""

import asyncio
import logging
from functools import wraps
from typing import Type, Tuple, Callable, Any

logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0


async def retry_async(
    coro_func: Callable[..., Any],
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    **kwargs
) -> Any:
    """Execute a coroutine with exponential backoff retry.

    Args:
        coro_func: Async function to call
        *args: Positional arguments for the function
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds (doubles each retry)
        retry_exceptions: Exception types to retry on
        **kwargs: Keyword arguments for the function

    Returns:
        Result of the coroutine

    Raises:
        Last exception if all retries fail
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except retry_exceptions as e:
            last_error = e
            if attempt == max_retries:
                logger.error(
                    "Retry exhausted after %s attempts: %s",
                    max_retries + 1,
                    e
                )
                raise

            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Attempt %s failed: %s. Retrying in %.1fs...",
                attempt + 1,
                e,
                delay
            )
            await asyncio.sleep(delay)

    raise last_error