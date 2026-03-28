"""Tests for McpBearerAuth — httpx.Auth integration with AuthProvider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from argus_mcp.bridge.auth.httpx_auth import _MAX_401_RETRIES, McpBearerAuth


def _make_provider(
    headers: dict[str, str] | None = None,
    *,
    side_effect: list[dict[str, str]] | None = None,
) -> MagicMock:
    """Return a mock AuthProvider with async get_headers and invalidate."""
    provider = MagicMock()
    if side_effect is not None:
        provider.get_headers = AsyncMock(side_effect=side_effect)
    else:
        provider.get_headers = AsyncMock(
            return_value=headers or {"Authorization": "Bearer tok1"},
        )
    provider.invalidate = MagicMock()
    return provider


async def _run_auth_flow(
    auth: McpBearerAuth,
    responses: list[httpx.Response],
) -> httpx.Response:
    """Drive the async_auth_flow generator with the given response sequence."""
    request = httpx.Request("GET", "https://backend.example.com/mcp")
    flow = auth.async_auth_flow(request)

    # First yield: the (possibly modified) request
    _outgoing = await flow.__anext__()

    for resp in responses:
        try:
            _outgoing = await flow.asend(resp)
        except StopAsyncIteration:
            return resp

    # After all responses consumed, exhaust the generator
    try:
        await flow.asend(responses[-1])
    except StopAsyncIteration:
        pass
    return responses[-1]


# Tests


class TestMcpBearerAuth:
    """Tests for McpBearerAuth."""

    @pytest.mark.asyncio
    async def test_injects_auth_header(self) -> None:
        provider = _make_provider({"Authorization": "Bearer mytoken"})
        auth = McpBearerAuth(provider)

        request = httpx.Request("GET", "https://example.com/mcp")
        flow = auth.async_auth_flow(request)

        outgoing = await flow.__anext__()
        assert outgoing.headers["Authorization"] == "Bearer mytoken"

        # Simulate a 200 OK — flow should complete
        resp = httpx.Response(200, request=request)
        with pytest.raises(StopAsyncIteration):
            await flow.asend(resp)

        provider.get_headers.assert_awaited_once()
        provider.invalidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_401(self) -> None:
        provider = _make_provider(
            side_effect=[
                {"Authorization": "Bearer old_token"},
                {"Authorization": "Bearer new_token"},
            ],
        )
        auth = McpBearerAuth(provider)

        request = httpx.Request("GET", "https://example.com/mcp")
        flow = auth.async_auth_flow(request)

        # First request
        outgoing = await flow.__anext__()
        assert outgoing.headers["Authorization"] == "Bearer old_token"

        # 401 response → should retry
        resp_401 = httpx.Response(401, request=request)
        outgoing = await flow.asend(resp_401)
        assert outgoing.headers["Authorization"] == "Bearer new_token"

        # Second attempt succeeds (200)
        resp_200 = httpx.Response(200, request=request)
        with pytest.raises(StopAsyncIteration):
            await flow.asend(resp_200)

        provider.invalidate.assert_called_once()
        assert provider.get_headers.await_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_respected(self) -> None:
        """After _MAX_401_RETRIES, stop retrying even if still 401."""
        # Provide enough headers for initial + max retries + 1
        headers_list = [{"Authorization": f"Bearer tok{i}"} for i in range(_MAX_401_RETRIES + 2)]
        provider = _make_provider(side_effect=headers_list)
        auth = McpBearerAuth(provider)

        request = httpx.Request("GET", "https://example.com/mcp")
        flow = auth.async_auth_flow(request)

        await flow.__anext__()

        for _ in range(_MAX_401_RETRIES):
            resp_401 = httpx.Response(401, request=request)
            await flow.asend(resp_401)

        # One more 401 should cause the generator to finish (no more retry)
        resp_401_final = httpx.Response(401, request=request)
        with pytest.raises(StopAsyncIteration):
            await flow.asend(resp_401_final)

        assert provider.invalidate.call_count == _MAX_401_RETRIES

    @pytest.mark.asyncio
    async def test_non_401_passes_through(self) -> None:
        provider = _make_provider({"Authorization": "Bearer tok"})
        auth = McpBearerAuth(provider)

        request = httpx.Request("GET", "https://example.com/mcp")
        flow = auth.async_auth_flow(request)

        await flow.__anext__()

        # 403 is NOT retried
        resp_403 = httpx.Response(403, request=request)
        with pytest.raises(StopAsyncIteration):
            await flow.asend(resp_403)

        provider.invalidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_class_attributes(self) -> None:
        assert McpBearerAuth.requires_request_body is False
        assert McpBearerAuth.requires_response_body is False


class TestMcpBearerAuthImport:
    """Ensure McpBearerAuth is exported from the auth package."""

    def test_importable_from_package(self) -> None:
        from argus_mcp.bridge.auth import McpBearerAuth as FromPkg

        assert FromPkg is McpBearerAuth
