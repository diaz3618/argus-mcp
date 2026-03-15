"""Tests for argus_mcp.server.app — ASGI application.

Covers:
- _MCPSlashMiddleware: intercepts exact path, passes others
- create_app returns Starlette instance
- Module-level mcp_server and streamable_session_manager
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class TestMCPSlashMiddleware:
    @pytest.mark.asyncio
    async def test_intercepts_exact_path(self) -> None:
        from argus_mcp.server.app import _MCPSlashMiddleware

        inner_app = AsyncMock()
        mcp_handler = AsyncMock()

        mw = _MCPSlashMiddleware(inner_app, mcp_path="/mcp", mcp_handler=mcp_handler)

        scope = {"type": "http", "path": "/mcp"}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        mcp_handler.assert_awaited_once_with(scope, receive, send)
        inner_app.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_other_paths(self) -> None:
        from argus_mcp.server.app import _MCPSlashMiddleware

        inner_app = AsyncMock()
        mcp_handler = AsyncMock()

        mw = _MCPSlashMiddleware(inner_app, mcp_path="/mcp", mcp_handler=mcp_handler)

        scope = {"type": "http", "path": "/sse"}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner_app.assert_awaited_once_with(scope, receive, send)
        mcp_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_non_http_scope(self) -> None:
        from argus_mcp.server.app import _MCPSlashMiddleware

        inner_app = AsyncMock()
        mcp_handler = AsyncMock()

        mw = _MCPSlashMiddleware(inner_app, mcp_path="/mcp", mcp_handler=mcp_handler)

        scope = {"type": "websocket", "path": "/mcp"}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner_app.assert_awaited_once()
        mcp_handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_trailing_slash_path(self) -> None:
        from argus_mcp.server.app import _MCPSlashMiddleware

        inner_app = AsyncMock()
        mcp_handler = AsyncMock()

        mw = _MCPSlashMiddleware(inner_app, mcp_path="/mcp", mcp_handler=mcp_handler)

        scope = {"type": "http", "path": "/mcp/"}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner_app.assert_awaited_once()
        mcp_handler.assert_not_awaited()


class TestModuleLevelInstances:
    def test_mcp_server_has_name(self) -> None:
        from argus_mcp.server.app import mcp_server

        assert mcp_server.name is not None

    def test_streamable_session_manager_initially_none(self) -> None:
        from argus_mcp.server.app import streamable_session_manager

        # Should be None at module import time (populated during lifespan)
        assert streamable_session_manager is None


class TestCreateApp:
    def test_returns_starlette_app(self) -> None:
        from starlette.applications import Starlette

        from argus_mcp.server.app import create_app

        application = create_app()
        assert isinstance(application, Starlette)
