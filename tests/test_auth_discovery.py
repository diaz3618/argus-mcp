"""Tests for argus_mcp.bridge.auth_discovery — OAuth discovery helpers."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.bridge.auth_discovery import (
    attempt_auth_discovery,
    dynamic_register,
    looks_like_auth_failure,
    resolve_auth_headers,
    try_auth_discovery,
)

# looks_like_auth_failure


class TestLooksLikeAuthFailure:
    """Unit tests for HTTP auth error detection."""

    def test_plain_401_string(self) -> None:
        assert looks_like_auth_failure(Exception("401 Unauthorized"))

    def test_plain_403_string(self) -> None:
        assert looks_like_auth_failure(Exception("403 Forbidden"))

    def test_unauthorized_keyword(self) -> None:
        assert looks_like_auth_failure(Exception("Server returned Unauthorized"))

    def test_unrelated_error(self) -> None:
        assert not looks_like_auth_failure(Exception("Connection timed out"))

    def test_httpx_status_error_401(self) -> None:
        """Simulate HTTPStatusError-style object without importing httpx."""
        exc = type("HTTPStatusError", (Exception,), {})("fail")
        resp = MagicMock(status_code=401)
        exc.response = resp  # type: ignore[attr-defined]
        assert looks_like_auth_failure(exc)

    def test_httpx_status_error_200(self) -> None:
        exc = type("HTTPStatusError", (Exception,), {})("ok")
        resp = MagicMock(status_code=200)
        exc.response = resp  # type: ignore[attr-defined]
        assert not looks_like_auth_failure(exc)

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="BaseExceptionGroup requires 3.11+")
    def test_exception_group_with_auth(self) -> None:
        inner = Exception("401 Unauthorized")
        group = BaseExceptionGroup("group", [inner])  # noqa: F821
        assert looks_like_auth_failure(group)

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="BaseExceptionGroup requires 3.11+")
    def test_exception_group_without_auth(self) -> None:
        inner = Exception("Some other error")
        group = BaseExceptionGroup("group", [inner])  # noqa: F821
        assert not looks_like_auth_failure(group)


# resolve_auth_headers


class TestResolveAuthHeaders:
    """Unit tests for auth header resolution."""

    @pytest.mark.asyncio
    async def test_no_auth_config_returns_none(self) -> None:
        result = await resolve_auth_headers("srv", {}, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_explicit_auth_block(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.get_headers.return_value = {"Authorization": "Bearer tok"}
        mock_provider.redacted_repr.return_value = "BearerProvider(***)"

        with patch(
            "argus_mcp.bridge.auth.provider.create_auth_provider",
            return_value=mock_provider,
        ) as factory:
            conf: Dict[str, Any] = {"auth": {"type": "bearer", "token": "tok"}}
            result = await resolve_auth_headers("srv", conf, {})
            assert result == {"Authorization": "Bearer tok"}
            factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovered_auth_fallback(self) -> None:
        mock_provider = AsyncMock()
        mock_provider.get_headers.return_value = {"Authorization": "Bearer disc"}
        mock_provider.redacted_repr.return_value = "Discovered"

        discovered: Dict[str, Dict[str, Any]] = {"srv": {"type": "bearer", "token": "disc"}}
        with patch(
            "argus_mcp.bridge.auth.provider.create_auth_provider",
            return_value=mock_provider,
        ):
            result = await resolve_auth_headers("srv", {}, discovered)
            assert result == {"Authorization": "Bearer disc"}

    @pytest.mark.asyncio
    async def test_provider_error_returns_none(self) -> None:
        with patch(
            "argus_mcp.bridge.auth.provider.create_auth_provider",
            side_effect=RuntimeError("bad"),
        ):
            conf: Dict[str, Any] = {"auth": {"type": "broken"}}
            result = await resolve_auth_headers("srv", conf, {})
            assert result is None


# attempt_auth_discovery


class TestAttemptAuthDiscovery:
    """Unit tests for deduplicated auth discovery orchestration."""

    @pytest.mark.asyncio
    async def test_skips_non_remote_type(self) -> None:
        reason = await attempt_auth_discovery("s", {}, "stdio", "original", {}, {})
        assert reason == "original"

    @pytest.mark.asyncio
    async def test_reuses_existing_task(self) -> None:
        async def _delayed_true() -> bool:
            await asyncio.sleep(0.01)
            return True

        task = asyncio.create_task(_delayed_true())
        tasks: Dict[str, asyncio.Task] = {"s": task}

        reason = await attempt_auth_discovery("s", {"url": "http://x"}, "sse", "fail", tasks, {})
        assert "already running" in reason

    @pytest.mark.asyncio
    async def test_new_task_created_on_success(self) -> None:
        tasks: Dict[str, asyncio.Task] = {}
        with patch(
            "argus_mcp.bridge.auth_discovery.try_auth_discovery",
            return_value=True,
        ):
            reason = await attempt_auth_discovery(
                "s", {"url": "http://x"}, "sse", "fail", tasks, {}
            )
            # Non-blocking: returns immediately with background task message
            assert "PKCE" in reason or "background" in reason.lower()
            assert "s" in tasks  # task was registered

    @pytest.mark.asyncio
    async def test_new_task_returns_default_on_failure(self) -> None:
        with patch(
            "argus_mcp.bridge.auth_discovery.try_auth_discovery",
            return_value=False,
        ):
            tasks: Dict[str, asyncio.Task] = {}
            reason = await attempt_auth_discovery(
                "s", {"url": "http://x"}, "streamable-http", "orig", tasks, {}
            )
            # Non-blocking: returns PKCE message (not default_reason)
            assert "PKCE" in reason or "background" in reason.lower()
            assert "s" in tasks  # task was still registered


# try_auth_discovery


class TestTryAuthDiscovery:
    """Unit tests for the core OAuth metadata probing flow."""

    @pytest.mark.asyncio
    async def test_no_url_returns_false(self) -> None:
        assert not await try_auth_discovery("s", {}, {})

    @pytest.mark.asyncio
    async def test_existing_auth_returns_false(self) -> None:
        conf: Dict[str, Any] = {"url": "http://x", "auth": {"type": "bearer"}}
        assert not await try_auth_discovery("s", conf, {})

    @pytest.mark.asyncio
    async def test_already_discovered_returns_false(self) -> None:
        conf: Dict[str, Any] = {"url": "http://x"}
        discovered: Dict[str, Dict[str, Any]] = {"s": {"type": "bearer"}}
        assert not await try_auth_discovery("s", conf, discovered)

    @pytest.mark.asyncio
    async def test_no_metadata_returns_false(self) -> None:
        with patch(
            "argus_mcp.bridge.auth.discovery.discover_oauth_metadata",
            return_value=None,
        ):
            assert not await try_auth_discovery("s", {"url": "http://x"}, {})


# dynamic_register


class TestDynamicRegister:
    """Unit tests for dynamic client registration."""

    @pytest.mark.asyncio
    async def test_successful_registration(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "client_id": "cid",
            "client_secret": "csec",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client):
            cid, csec = await dynamic_register(
                "srv", "https://reg.example.com", "https://backend.example.com"
            )
            assert cid == "cid"
            assert csec == "csec"
