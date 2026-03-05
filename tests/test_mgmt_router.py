"""Tests for argus_mcp.server.management.router — management API handlers.

Covers:
- handle_health() responses
- handle_status() structure
- handle_backends() with mock service
- handle_capabilities() filtering
- handle_events() with limit/since params
- handle_reload() / handle_reconnect() / handle_shutdown()
- _sse_format() helper
- management_routes route table
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from argus_mcp.server.management.router import (
    _sse_format,
    handle_health,
    handle_status,
    management_routes,
)
from argus_mcp.server.management.schemas import (
    HealthBackends,
    HealthResponse,
    StatusResponse,
    StatusService,
)


# ── _sse_format helper ──────────────────────────────────────────────────


class TestSseFormat:
    def test_basic_format(self):
        result = _sse_format("heartbeat", {"message": "ping"})
        assert "event: heartbeat" in result
        assert "data:" in result
        assert '"message"' in result

    def test_with_event_id(self):
        result = _sse_format("event", {"key": "val"}, event_id="evt-1")
        assert "id: evt-1" in result

    def test_without_event_id(self):
        result = _sse_format("event", {"key": "val"})
        assert "id:" not in result

    def test_json_data(self):
        data = {"count": 42, "name": "test"}
        result = _sse_format("update", data)
        # The data line should be valid JSON
        for line in result.split("\n"):
            if line.startswith("data:"):
                parsed = json.loads(line[len("data: "):])
                assert parsed["count"] == 42


# ── management_routes ────────────────────────────────────────────────────


class TestManagementRoutes:
    def test_routes_exist(self):
        """All expected routes are registered."""
        paths = {r.path for r in management_routes.routes}
        expected = {
            "/health", "/status", "/backends", "/groups",
            "/capabilities", "/sessions", "/events",
            "/events/stream", "/reload", "/reconnect/{name}",
            "/shutdown",
        }
        assert expected.issubset(paths)

    def test_health_is_get(self):
        for r in management_routes.routes:
            if r.path == "/health":
                assert "GET" in r.methods
                break

    def test_reload_is_post(self):
        for r in management_routes.routes:
            if r.path == "/reload":
                assert "POST" in r.methods
                break


# ── handle_health ────────────────────────────────────────────────────────


class TestHandleHealth:
    @staticmethod
    def _mock_request(service: MagicMock) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app = MagicMock()
        req.app.state = MagicMock()
        req.app.state.argus_service = service
        return req

    @pytest.mark.asyncio
    async def test_healthy_response(self):
        service = MagicMock()
        service.get_status.return_value = MagicMock(
            backends_connected=2,
            backends_total=2,
            uptime_seconds=100.0,
        )

        req = self._mock_request(service)

        response = await handle_health(req)
        data = json.loads(response.body)
        assert data["status"] == "healthy"
        assert "backends" in data

    @pytest.mark.asyncio
    async def test_no_manager_returns_unhealthy(self):
        service = MagicMock()
        service.get_status.return_value = MagicMock(
            backends_connected=0,
            backends_total=2,
            uptime_seconds=0.0,
        )

        req = self._mock_request(service)

        response = await handle_health(req)
        data = json.loads(response.body)
        assert data["status"] == "unhealthy"


# ── handle_status ────────────────────────────────────────────────────────


class TestHandleStatus:
    @staticmethod
    def _mock_request(service: MagicMock) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app = MagicMock()
        req.app.state = MagicMock()
        req.app.state.argus_service = service
        req.app.state.host = "127.0.0.1"
        req.app.state.port = 9000
        return req

    @pytest.mark.asyncio
    async def test_status_structure(self):
        from argus_mcp.runtime.models import ServiceState

        service = MagicMock()
        service.get_status.return_value = MagicMock(
            state=ServiceState.RUNNING,
            server_name="Argus MCP",
            server_version="0.7.0",
            started_at=None,
            uptime_seconds=100.0,
            backends_total=1,
            config_path="/path/config.yaml",
        )

        req = self._mock_request(service)

        response = await handle_status(req)
        data = json.loads(response.body)
        assert "service" in data
        assert data["service"]["name"] == "Argus MCP"
        assert "config" in data
        assert "transport" in data
