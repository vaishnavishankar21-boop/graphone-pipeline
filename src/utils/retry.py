"""
Shared async retry/backoff utility.

Used by every network-calling component in the pipeline: scrapers, the
GitHub stars enrichment step, and the LLM orchestrator's fallback chain.

Handles:
- 429 Too Many Requests -> exponential backoff + jitter, honors Retry-After
- 5xx transient errors -> retry
- 413 Payload Too Large -> NOT retried here (that's a payload problem, not
  a transient one — see llm/chunking.py for the fix)
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional, TypeVar

import aiohttp

logger = logging.getLogger("graphone.retry")

T = TypeVar("T")


class RetryableError(Exception):
    """Raised by callers to force a retry (e.g. rate limited)."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(Exception):
    """Raised by callers to signal 'don't bother retrying this one'."""


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: float = 0.5,
    op_name: str = "operation",
) -> T:
    """
    Runs `fn` with exponential backoff + jitter on RetryableError,
    aiohttp.ClientError, and asyncio.TimeoutError.

    Backoff formula: min(max_delay, base_delay * 2^attempt) + random jitter.
    If the error carries a Retry-After (429 responses), that value is
    respected instead of the computed backoff.
    """
    attempt = 0
    while True:
        try:
            return await fn()
        except RetryableError as e:
            attempt += 1
            if attempt >= max_attempts:
                logger.error(f"[{op_name}] giving up after {attempt} attempts: {e}")
                raise
            delay = e.retry_after if e.retry_after else min(max_delay, base_delay * (2 ** attempt))
            delay += random.uniform(0, jitter)
            logger.warning(f"[{op_name}] retryable error (attempt {attempt}/{max_attempts}), "
                            f"sleeping {delay:.1f}s: {e}")
            await asyncio.sleep(delay)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            attempt += 1
            if attempt >= max_attempts:
                logger.error(f"[{op_name}] giving up after {attempt} attempts: {e}")
                raise
            delay = min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, jitter)
            logger.warning(f"[{op_name}] network error (attempt {attempt}/{max_attempts}), "
                            f"sleeping {delay:.1f}s: {e}")
            await asyncio.sleep(delay)
        except PermanentError as e:
            logger.error(f"[{op_name}] permanent error, not retrying: {e}")
            raise


def parse_retry_after(response: aiohttp.ClientResponse) -> Optional[float]:
    """Extract Retry-After header (seconds) from a 429/503 response, if present."""
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None
