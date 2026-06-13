from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Any:
    """Retry a synchronous callable with exponential backoff and jitter.

    On each retry the delay doubles, capped at *max_delay*, with a small
    random jitter to avoid thundering-herd effects.

    Args:
        func: Synchronous callable to retry.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds between retries.
        retryable_exceptions: Exception types that trigger a retry.

    Returns:
        The return value of *func* on success.

    Raises:
        The last encountered exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = min(base_delay * (2**attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            wait = delay + jitter
            logger.warning(
                "Attempt %d/%d failed: %s; retrying in %.1fs",
                attempt + 1,
                max_retries + 1,
                exc,
                wait,
            )
            time.sleep(wait)

    assert last_exc is not None
    raise last_exc


async def async_retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Any:
    """Retry an async callable with exponential backoff and jitter.

    On each retry the delay doubles, capped at *max_delay*, with a small
    random jitter to avoid thundering-herd effects.

    Args:
        func: Async callable to retry.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds between retries.
        retryable_exceptions: Exception types that trigger a retry.

    Returns:
        The return value of *func* on success.

    Raises:
        The last encountered exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = min(base_delay * (2**attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            wait = delay + jitter
            logger.warning(
                "Attempt %d/%d failed: %s; retrying in %.1fs",
                attempt + 1,
                max_retries + 1,
                exc,
                wait,
            )
            await asyncio.sleep(wait)

    assert last_exc is not None
    raise last_exc
