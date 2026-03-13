"""Resilient HTTP retry manager with categorised error handling.

Classifies HTTP status codes into *retryable* (429, 502, 503, 504, 408) and
*non-retryable* (400, 401, 403, 404) categories.  Retryable requests are
retried with exponential backoff plus jitter, and ``429 Retry-After`` headers
are respected.

Usage::

    retry = RetryManager(max_retries=3, base_delay=1.0, backoff=2.0)

    response = await retry.execute(pool.client, "GET", "https://example.com/api")

The manager is stateless per-call — each :meth:`execute` invocation carries
its own retry counter.  Integrate with :class:`HttpPool` for connection
reuse::

    pool = HttpPool()
    await pool.start()
    retry = RetryManager()
    resp = await retry.execute(pool.client, "GET", url)
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, Optional, Set

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES: Set[int] = {408, 429, 502, 503, 504}
"""HTTP status codes that warrant automatic retry."""

NON_RETRYABLE_STATUS_CODES: Set[int] = {400, 401, 403, 404}
"""HTTP status codes that should never be retried."""

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_MAX_DELAY = 60.0  # cap on computed delay
DEFAULT_JITTER_RANGE = 0.5  # ± fraction of delay used for jitter


class NonRetryableError(Exception):
    """Raised when a request fails with a non-retryable status code."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"Non-retryable HTTP {status_code}")


class RetriesExhaustedError(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, last_status: int, attempts: int) -> None:
        self.last_status = last_status
        self.attempts = attempts
        super().__init__(
            f"Retries exhausted after {attempts} attempt(s), last status {last_status}"
        )


class RetryManager:
    """HTTP retry manager with exponential backoff and jitter.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts (*not* counting the initial request).
    base_delay:
        Initial delay in seconds before the first retry.
    backoff_factor:
        Multiplier applied to the delay after each retry.
    max_delay:
        Upper bound on computed delay in seconds.
    jitter:
        Fraction (0.0–1.0) of the delay used for random jitter.
    """

    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER_RANGE,
    ) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._backoff_factor = backoff_factor
        self._max_delay = max_delay
        self._jitter = jitter

    async def execute(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        content: Optional[bytes] = None,
        json: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Send an HTTP request with automatic retry on retryable failures.

        Raises
        ------
        NonRetryableError
            If the server returns a non-retryable status code.
        RetriesExhaustedError
            If all retry attempts fail with retryable status codes.
        httpx.HTTPError
            If a transport-level error occurs on the final attempt.
        """
        last_status = 0

        for attempt in range(1, self._max_retries + 2):  # +2: initial + retries
            try:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    content=content,
                    json=json,
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                # Transport errors (connection refused, timeout, DNS) are retryable
                if attempt > self._max_retries:
                    raise
                logger.warning(
                    "HTTP %s %s attempt %d/%d failed with %s — retrying.",
                    method,
                    url,
                    attempt,
                    self._max_retries + 1,
                    type(exc).__name__,
                )
                await self._wait(attempt, retry_after=None)
                continue

            status = response.status_code

            # Success
            if 200 <= status < 300:
                return response

            # Non-retryable — fail immediately
            if status in NON_RETRYABLE_STATUS_CODES:
                raise NonRetryableError(status)

            # Retryable — check budget
            if status in RETRYABLE_STATUS_CODES:
                last_status = status
                if attempt > self._max_retries:
                    raise RetriesExhaustedError(last_status=status, attempts=attempt)

                retry_after = self._parse_retry_after(response)
                logger.warning(
                    "HTTP %s %s returned %d on attempt %d/%d — retrying.",
                    method,
                    url,
                    status,
                    attempt,
                    self._max_retries + 1,
                )
                await self._wait(attempt, retry_after=retry_after)
                continue

            # Unknown status — treat as non-retryable
            raise NonRetryableError(status, f"Unexpected HTTP {status}")

        # Should not reach here, but satisfy type checker
        raise RetriesExhaustedError(last_status=last_status, attempts=self._max_retries + 1)

    async def _wait(self, attempt: int, *, retry_after: Optional[float]) -> None:
        """Sleep with exponential backoff + jitter, or honour Retry-After."""
        if retry_after is not None and retry_after > 0:
            delay = min(retry_after, self._max_delay)
        else:
            delay = self._base_delay * (self._backoff_factor ** (attempt - 1))
            delay = min(delay, self._max_delay)
            # Add jitter: delay ± jitter*delay
            jitter_amount = delay * self._jitter
            delay += random.uniform(-jitter_amount, jitter_amount)  # noqa: S311
            delay = max(0.01, delay)  # never negative

        logger.debug("Retry wait: %.2fs (attempt %d).", delay, attempt)
        await asyncio.sleep(delay)

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> Optional[float]:
        """Extract ``Retry-After`` header value in seconds, if present."""
        raw = response.headers.get("retry-after")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            # RFC 7231 §7.1.3 also allows HTTP-date — we only handle delta-seconds
            logger.debug("Ignoring non-numeric Retry-After header: %s", raw)
            return None
