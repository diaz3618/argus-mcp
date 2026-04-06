"""Tests for argus_mcp.bridge.retry — RetryManager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from argus_mcp.bridge.retry import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BASE_DELAY,
    DEFAULT_JITTER_RANGE,
    DEFAULT_MAX_DELAY,
    DEFAULT_MAX_RETRIES,
    NON_RETRYABLE_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    NonRetryableError,
    RetriesExhaustedError,
    RetryManager,
)
from argus_mcp.config.schema import RetryConfig


def _mock_response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    """Create a minimal httpx.Response with the given status code."""
    resp = httpx.Response(status_code=status, headers=headers or {})
    return resp


def _mock_client(*responses: httpx.Response) -> httpx.AsyncClient:
    """Return a mock AsyncClient whose .request() yields responses in order."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(side_effect=list(responses))
    return client


# Constants tests


class TestStatusCodeClassification:
    """Verify the status code sets are correct."""

    def test_retryable_codes(self) -> None:
        assert RETRYABLE_STATUS_CODES == {408, 429, 502, 503, 504}

    def test_non_retryable_codes(self) -> None:
        assert NON_RETRYABLE_STATUS_CODES == {400, 401, 403, 404}

    def test_no_overlap(self) -> None:
        assert RETRYABLE_STATUS_CODES.isdisjoint(NON_RETRYABLE_STATUS_CODES)


# Defaults tests


class TestDefaults:
    """Verify default parameter values on RetryManager."""

    def test_defaults(self) -> None:
        rm = RetryManager()
        assert rm._max_retries == DEFAULT_MAX_RETRIES
        assert rm._base_delay == DEFAULT_BASE_DELAY
        assert rm._backoff_factor == DEFAULT_BACKOFF_FACTOR
        assert rm._max_delay == DEFAULT_MAX_DELAY
        assert rm._jitter == DEFAULT_JITTER_RANGE

    def test_custom_params(self) -> None:
        rm = RetryManager(
            max_retries=5,
            base_delay=0.5,
            backoff_factor=3.0,
            max_delay=120.0,
            jitter=0.2,
        )
        assert rm._max_retries == 5
        assert rm._base_delay == 0.5
        assert rm._backoff_factor == 3.0
        assert rm._max_delay == 120.0
        assert rm._jitter == 0.2


# Success path


class TestSuccessPath:
    """Test that successful requests return immediately."""

    async def test_200_no_retry(self) -> None:
        client = _mock_client(_mock_response(200))
        rm = RetryManager()
        resp = await rm.execute(client, "GET", "https://example.com")
        assert resp.status_code == 200
        assert client.request.call_count == 1

    async def test_201_no_retry(self) -> None:
        client = _mock_client(_mock_response(201))
        rm = RetryManager()
        resp = await rm.execute(client, "POST", "https://example.com")
        assert resp.status_code == 201


# Non-retryable errors


class TestNonRetryable:
    """Non-retryable status codes should raise immediately."""

    @pytest.mark.parametrize("status", sorted(NON_RETRYABLE_STATUS_CODES))
    async def test_non_retryable_raises(self, status: int) -> None:
        client = _mock_client(_mock_response(status))
        rm = RetryManager()
        with pytest.raises(NonRetryableError) as exc_info:
            await rm.execute(client, "GET", "https://example.com")
        assert exc_info.value.status_code == status
        assert client.request.call_count == 1

    async def test_unknown_status_raises(self) -> None:
        client = _mock_client(_mock_response(418))
        rm = RetryManager()
        with pytest.raises(NonRetryableError) as exc_info:
            await rm.execute(client, "GET", "https://example.com")
        assert exc_info.value.status_code == 418


# Retryable errors


class TestRetryable:
    """Retryable status codes should be retried up to max_retries times."""

    @pytest.mark.parametrize("status", sorted(RETRYABLE_STATUS_CODES))
    async def test_retryable_exhausts(self, status: int) -> None:
        responses = [_mock_response(status)] * 4  # initial + 3 retries
        client = _mock_client(*responses)
        rm = RetryManager(max_retries=3, base_delay=0.01, jitter=0.0)
        with pytest.raises(RetriesExhaustedError) as exc_info:
            await rm.execute(client, "GET", "https://example.com")
        assert exc_info.value.last_status == status
        assert exc_info.value.attempts == 4
        assert client.request.call_count == 4

    async def test_retryable_then_success(self) -> None:
        responses = [
            _mock_response(503),
            _mock_response(503),
            _mock_response(200),
        ]
        client = _mock_client(*responses)
        rm = RetryManager(max_retries=3, base_delay=0.01, jitter=0.0)
        resp = await rm.execute(client, "GET", "https://example.com")
        assert resp.status_code == 200
        assert client.request.call_count == 3


# 429 Retry-After


class TestRetryAfter:
    """Verify that Retry-After headers are respected."""

    async def test_retry_after_numeric(self) -> None:
        responses = [
            _mock_response(429, headers={"retry-after": "0.01"}),
            _mock_response(200),
        ]
        client = _mock_client(*responses)
        rm = RetryManager(max_retries=3, base_delay=10.0, jitter=0.0)
        resp = await rm.execute(client, "GET", "https://example.com")
        assert resp.status_code == 200

    async def test_retry_after_non_numeric_ignored(self) -> None:
        responses = [
            _mock_response(429, headers={"retry-after": "Wed, 01 Jan 2025 00:00:00 GMT"}),
            _mock_response(200),
        ]
        client = _mock_client(*responses)
        rm = RetryManager(max_retries=3, base_delay=0.01, jitter=0.0)
        resp = await rm.execute(client, "GET", "https://example.com")
        assert resp.status_code == 200


# Transport errors


class TestTransportErrors:
    """Transport-level errors (connection, timeout) should be retried."""

    async def test_connection_error_retried(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(
            side_effect=[
                httpx.ConnectError("refused"),
                _mock_response(200),
            ]
        )
        rm = RetryManager(max_retries=3, base_delay=0.01, jitter=0.0)
        resp = await rm.execute(client, "GET", "https://example.com")
        assert resp.status_code == 200
        assert client.request.call_count == 2

    async def test_transport_error_exhausted(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=httpx.ConnectError("refused"))
        rm = RetryManager(max_retries=2, base_delay=0.01, jitter=0.0)
        with pytest.raises(httpx.ConnectError):
            await rm.execute(client, "GET", "https://example.com")
        assert client.request.call_count == 3  # initial + 2 retries


# Backoff and jitter


class TestBackoff:
    """Verify exponential backoff computation."""

    async def test_backoff_increases(self) -> None:
        """With jitter=0 the delays should follow exact exponential pattern."""
        delays: list[float] = []
        _original_sleep = asyncio.sleep

        async def mock_sleep(seconds: float) -> None:
            delays.append(seconds)

        responses = [_mock_response(503)] * 4
        client = _mock_client(*responses)
        rm = RetryManager(max_retries=3, base_delay=1.0, backoff_factor=2.0, jitter=0.0)

        with patch("argus_mcp.bridge.retry.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(RetriesExhaustedError):
                await rm.execute(client, "GET", "https://example.com")

        # Delays: 1.0, 2.0, 4.0
        assert len(delays) == 3
        assert delays[0] == pytest.approx(1.0)
        assert delays[1] == pytest.approx(2.0)
        assert delays[2] == pytest.approx(4.0)

    async def test_max_delay_cap(self) -> None:
        """Delay should never exceed max_delay."""
        delays: list[float] = []

        async def mock_sleep(seconds: float) -> None:
            delays.append(seconds)

        responses = [_mock_response(503)] * 4
        client = _mock_client(*responses)
        rm = RetryManager(
            max_retries=3, base_delay=10.0, backoff_factor=3.0, max_delay=20.0, jitter=0.0
        )

        with patch("argus_mcp.bridge.retry.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(RetriesExhaustedError):
                await rm.execute(client, "GET", "https://example.com")

        for d in delays:
            assert d <= 20.0


# Exception types


class TestExceptions:
    """Verify exception attributes."""

    def test_non_retryable_error(self) -> None:
        exc = NonRetryableError(403, "Forbidden")
        assert exc.status_code == 403
        assert "Forbidden" in str(exc)

    def test_non_retryable_error_default_msg(self) -> None:
        exc = NonRetryableError(401)
        assert exc.status_code == 401
        assert "401" in str(exc)

    def test_retries_exhausted_error(self) -> None:
        exc = RetriesExhaustedError(last_status=503, attempts=4)
        assert exc.last_status == 503
        assert exc.attempts == 4
        assert "503" in str(exc)


# Config model tests


class TestRetryConfig:
    """Verify Pydantic config model validation."""

    def test_defaults(self) -> None:
        cfg = RetryConfig()
        assert cfg.enabled is True
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.backoff_factor == 2.0
        assert cfg.max_delay == 60.0
        assert cfg.jitter == 0.5

    def test_custom_values(self) -> None:
        cfg = RetryConfig(max_retries=5, base_delay=2.0, backoff_factor=3.0)
        assert cfg.max_retries == 5
        assert cfg.base_delay == 2.0
        assert cfg.backoff_factor == 3.0

    def test_validation_bounds(self) -> None:
        with pytest.raises(Exception):
            RetryConfig(max_retries=-1)
        with pytest.raises(Exception):
            RetryConfig(max_retries=11)
        with pytest.raises(Exception):
            RetryConfig(base_delay=0.0)
        with pytest.raises(Exception):
            RetryConfig(jitter=1.5)

    def test_in_argus_config(self) -> None:
        from argus_mcp.config.schema import ArgusConfig

        cfg = ArgusConfig()
        assert isinstance(cfg.retry, RetryConfig)
        assert cfg.retry.enabled is True


# Request parameters forwarding


class TestRequestForwarding:
    """Verify that execute() forwards parameters to client.request()."""

    async def test_forwards_all_params(self) -> None:
        client = _mock_client(_mock_response(200))
        rm = RetryManager()
        await rm.execute(
            client,
            "POST",
            "https://example.com/api",
            headers={"X-Custom": "val"},
            content=b"body",
            timeout=5.0,
        )
        client.request.assert_called_once_with(
            "POST",
            "https://example.com/api",
            headers={"X-Custom": "val"},
            content=b"body",
            json=None,
            timeout=5.0,
        )

    async def test_forwards_json(self) -> None:
        client = _mock_client(_mock_response(200))
        rm = RetryManager()
        await rm.execute(
            client,
            "POST",
            "https://example.com/api",
            json={"key": "value"},
        )
        call_kwargs = client.request.call_args
        assert call_kwargs.kwargs["json"] == {"key": "value"}
