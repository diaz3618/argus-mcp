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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from argus_mcp.server.management.router import (
    _error_json,
    _get_service,
    _sse_format,
    handle_backends,
    handle_capabilities,
    handle_events,
    handle_groups,
    handle_health,
    handle_reconnect,
    handle_reload,
    handle_sessions,
    handle_shutdown,
    handle_status,
    management_routes,
)

# _sse_format helper ─────────────────────────────────────────────────


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
                parsed = json.loads(line[len("data: ") :])
                assert parsed["count"] == 42


# management_routes ───────────────────────────────────────────────────


class TestManagementRoutes:
    def test_routes_exist(self):
        """All expected routes are registered."""
        paths = {r.path for r in management_routes.routes}
        expected = {
            "/health",
            "/status",
            "/backends",
            "/groups",
            "/capabilities",
            "/sessions",
            "/events",
            "/events/stream",
            "/reload",
            "/reconnect/{name}",
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


# handle_health ───────────────────────────────────────────────────────


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


# handle_status ───────────────────────────────────────────────────────


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


# _get_service / _error_json helpers ──────────────────────────────────


class TestGetService:
    def test_returns_service(self):
        service = MagicMock()
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        assert _get_service(req) is service

    def test_raises_when_missing(self):
        req = MagicMock(spec=Request)
        req.app.state.argus_service = None
        with pytest.raises(RuntimeError, match="ArgusService not found"):
            _get_service(req)


class TestErrorJson:
    def test_default_status(self):
        resp = _error_json("oops", "something broke")
        data = json.loads(resp.body)
        assert data["error"] == "oops"
        assert data["message"] == "something broke"
        assert resp.status_code == 500

    def test_custom_status(self):
        resp = _error_json("bad", "bad request", 400)
        assert resp.status_code == 400


# handle_health — additional scenarios ────────────────────────────────


class TestHandleHealthExtra:
    @staticmethod
    def _mock_request(service: MagicMock) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        return req

    @pytest.mark.asyncio
    async def test_degraded_response(self):
        service = MagicMock()
        service.get_status.return_value = MagicMock(
            backends_connected=1,
            backends_total=3,
            uptime_seconds=50.0,
        )
        resp = await handle_health(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_healthy_no_backends(self):
        service = MagicMock()
        service.get_status.return_value = MagicMock(
            backends_connected=0,
            backends_total=0,
            uptime_seconds=10.0,
        )
        resp = await handle_health(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["status"] == "healthy"


# handle_backends ─────────────────────────────────────────────────────


class TestHandleBackends:
    @staticmethod
    def _mock_request(service: MagicMock) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        return req

    @pytest.mark.asyncio
    async def test_empty_backends(self):
        service = MagicMock()
        service.registry.get_route_map.return_value = {}
        service.tools = []
        service.resources = []
        service.prompts = []
        service.get_status.return_value = MagicMock(backends=[])
        service.health_checker = None

        resp = await handle_backends(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["backends"] == []

    @pytest.mark.asyncio
    async def test_single_backend(self):
        from argus_mcp.runtime.models import BackendInfo

        service = MagicMock()
        service.registry.get_route_map.return_value = {}
        service.tools = []
        service.resources = []
        service.prompts = []
        service.group_manager = None
        service.manager = None
        service.health_checker = None
        service.get_status.return_value = MagicMock(
            backends=[BackendInfo(name="be1", type="stdio", connected=True)]
        )

        resp = await handle_backends(self._mock_request(service))
        data = json.loads(resp.body)
        assert len(data["backends"]) == 1
        assert data["backends"][0]["name"] == "be1"
        assert data["backends"][0]["state"] == "connected"

    @pytest.mark.asyncio
    async def test_backend_with_health_checker(self):
        from argus_mcp.runtime.models import BackendInfo

        service = MagicMock()
        service.registry.get_route_map.return_value = {}
        service.tools = []
        service.resources = []
        service.prompts = []
        service.group_manager = None
        service.manager = None

        bh_mock = MagicMock()
        bh_mock.state.value = "healthy"
        bh_mock.to_dict.return_value = {"status": "healthy", "latency": 42}
        service.health_checker = MagicMock()
        service.health_checker.get_health.return_value = bh_mock

        service.get_status.return_value = MagicMock(
            backends=[BackendInfo(name="be1", type="stdio", connected=True)]
        )

        resp = await handle_backends(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["backends"][0]["health"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_backend_with_group_and_status_record(self):
        from argus_mcp.runtime.models import BackendInfo

        service = MagicMock()
        service.registry.get_route_map.return_value = {}
        service.tools = []
        service.resources = []
        service.prompts = []

        # Mock group manager
        gm = MagicMock()
        gm.group_of.return_value = "team-a"
        service.group_manager = gm

        # Mock status record
        sr = MagicMock()
        sr.phase.value = "ready"
        sr.error = None
        sr.recent_conditions = []
        cm = MagicMock()
        cm.get_status_record.return_value = sr
        service.manager = cm

        service.health_checker = None
        service.get_status.return_value = MagicMock(
            backends=[BackendInfo(name="be1", type="stdio", connected=True)]
        )

        resp = await handle_backends(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["backends"][0]["group"] == "team-a"
        assert data["backends"][0]["phase"] == "ready"


# handle_groups ───────────────────────────────────────────────────────


class TestHandleGroups:
    @staticmethod
    def _mock_request(service: MagicMock, query_params=None) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        req.query_params = query_params or {}
        return req

    @pytest.mark.asyncio
    async def test_no_group_manager(self):
        service = MagicMock()
        service.group_manager = None
        resp = await handle_groups(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["total_groups"] == 0

    @pytest.mark.asyncio
    async def test_filter_group(self):
        service = MagicMock()
        gm = MagicMock()
        gm.servers_in.return_value = ["s1", "s2"]
        service.group_manager = gm

        resp = await handle_groups(self._mock_request(service, {"group": "team-a"}))
        data = json.loads(resp.body)
        assert data["total_servers"] == 2
        assert "team-a" in data["groups"]

    @pytest.mark.asyncio
    async def test_all_groups(self):
        service = MagicMock()
        gm = MagicMock()
        gm.to_dict.return_value = {
            "groups": {"default": {"servers": ["s1"], "count": 1}},
            "total_groups": 1,
            "total_servers": 1,
        }
        service.group_manager = gm

        resp = await handle_groups(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["total_groups"] == 1


# handle_capabilities ────────────────────────────────────────────────


class TestHandleCapabilities:
    @staticmethod
    def _mock_request(service: MagicMock, query_params=None) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        req.query_params = query_params or {}
        return req

    @pytest.mark.asyncio
    async def test_empty_capabilities(self):
        service = MagicMock()
        service.registry.get_route_map.return_value = {}
        service.tools = []
        service.resources = []
        service.prompts = []

        resp = await handle_capabilities(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["tools"] == []
        assert data["resources"] == []
        assert data["prompts"] == []

    @pytest.mark.asyncio
    async def test_tools_listed(self):
        tool = MagicMock()
        tool.name = "my-tool"
        tool.description = "does stuff"
        tool.inputSchema = {"type": "object"}

        service = MagicMock()
        service.registry.get_route_map.return_value = {"my-tool": ("backend1", "orig-name")}
        service.tools = [tool]
        service.resources = []
        service.prompts = []

        resp = await handle_capabilities(self._mock_request(service))
        data = json.loads(resp.body)
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "my-tool"
        assert data["tools"][0]["backend"] == "backend1"

    @pytest.mark.asyncio
    async def test_filter_by_type(self):
        tool = MagicMock()
        tool.name = "my-tool"
        tool.description = ""
        tool.inputSchema = {}

        service = MagicMock()
        service.registry.get_route_map.return_value = {"my-tool": ("b", "t")}
        service.tools = [tool]
        service.resources = []
        service.prompts = []

        # Filter to only resources — tools should be excluded
        resp = await handle_capabilities(self._mock_request(service, {"type": "resources"}))
        data = json.loads(resp.body)
        assert data["tools"] == []

    @pytest.mark.asyncio
    async def test_filter_by_backend(self):
        tool1 = MagicMock()
        tool1.name = "t1"
        tool1.description = ""
        tool1.inputSchema = {}

        tool2 = MagicMock()
        tool2.name = "t2"
        tool2.description = ""
        tool2.inputSchema = {}

        service = MagicMock()
        service.registry.get_route_map.return_value = {
            "t1": ("backend1", "t1"),
            "t2": ("backend2", "t2"),
        }
        service.tools = [tool1, tool2]
        service.resources = []
        service.prompts = []

        resp = await handle_capabilities(self._mock_request(service, {"backend": "backend1"}))
        data = json.loads(resp.body)
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "t1"

    @pytest.mark.asyncio
    async def test_filter_by_search(self):
        tool = MagicMock()
        tool.name = "search-widget"
        tool.description = ""
        tool.inputSchema = {}

        service = MagicMock()
        service.registry.get_route_map.return_value = {"search-widget": ("b", "sw")}
        service.tools = [tool]
        service.resources = []
        service.prompts = []

        resp = await handle_capabilities(self._mock_request(service, {"search": "widget"}))
        data = json.loads(resp.body)
        assert len(data["tools"]) == 1

        resp2 = await handle_capabilities(self._mock_request(service, {"search": "nomatch"}))
        data2 = json.loads(resp2.body)
        assert len(data2["tools"]) == 0


# handle_events ───────────────────────────────────────────────────────


class TestHandleEvents:
    @staticmethod
    def _mock_request(service: MagicMock, query_params=None) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        req.query_params = query_params or {}
        return req

    @pytest.mark.asyncio
    async def test_returns_events(self):
        service = MagicMock()
        service.get_events.return_value = [
            {
                "id": "e1",
                "timestamp": "2024-01-01T00:00:00",
                "stage": "startup",
                "message": "started",
                "severity": "info",
            }
        ]

        resp = await handle_events(self._mock_request(service))
        data = json.loads(resp.body)
        assert len(data["events"]) == 1
        assert data["events"][0]["id"] == "e1"

    @pytest.mark.asyncio
    async def test_invalid_limit(self):
        service = MagicMock()
        resp = await handle_events(self._mock_request(service, {"limit": "abc"}))
        assert resp.status_code == 400
        data = json.loads(resp.body)
        assert data["error"] == "bad_request"

    @pytest.mark.asyncio
    async def test_limit_out_of_range(self):
        service = MagicMock()
        resp = await handle_events(self._mock_request(service, {"limit": "0"}))
        assert resp.status_code == 400


# handle_reload ───────────────────────────────────────────────────────


class TestHandleReload:
    @staticmethod
    def _mock_request(service: MagicMock) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        return req

    @pytest.mark.asyncio
    async def test_reload_success(self):
        service = MagicMock()
        service.is_running = True
        service.reload = AsyncMock(
            return_value={"reloaded": True, "added": [], "removed": [], "changed": []}
        )

        resp = await handle_reload(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["reloaded"] is True

    @pytest.mark.asyncio
    async def test_reload_not_running(self):
        service = MagicMock()
        service.is_running = False

        resp = await handle_reload(self._mock_request(service))
        assert resp.status_code == 503


# handle_reconnect ────────────────────────────────────────────────────


class TestHandleReconnect:
    @staticmethod
    def _mock_request(service: MagicMock, name: str = "be1") -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        req.path_params = {"name": name}
        return req

    @pytest.mark.asyncio
    async def test_reconnect_success(self):
        service = MagicMock()
        service.is_running = True
        service.config_data = {"be1": {}}
        service.reconnect_backend = AsyncMock(return_value={"reconnected": True, "name": "be1"})

        resp = await handle_reconnect(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["reconnected"] is True

    @pytest.mark.asyncio
    async def test_reconnect_empty_name(self):
        service = MagicMock()
        resp = await handle_reconnect(self._mock_request(service, name=""))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reconnect_name_too_long(self):
        service = MagicMock()
        long_name = "x" * 300
        resp = await handle_reconnect(self._mock_request(service, name=long_name))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reconnect_not_running(self):
        service = MagicMock()
        service.is_running = False
        resp = await handle_reconnect(self._mock_request(service, name="be1"))
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_reconnect_not_found(self):
        service = MagicMock()
        service.is_running = True
        service.config_data = {"other": {}}
        resp = await handle_reconnect(self._mock_request(service, name="missing"))
        assert resp.status_code == 404


# handle_shutdown ─────────────────────────────────────────────────────


class TestHandleShutdown:
    @staticmethod
    def _mock_request(service: MagicMock, body=None) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        if body is not None:
            req.json = AsyncMock(return_value=body)
        else:
            req.json = AsyncMock(side_effect=ValueError("no body"))
        return req

    @pytest.mark.asyncio
    async def test_shutdown_default_timeout(self):
        service = MagicMock()
        service.shutdown = AsyncMock()

        resp = await handle_shutdown(self._mock_request(service))
        data = json.loads(resp.body)
        assert data["shutting_down"] is True

    @pytest.mark.asyncio
    async def test_shutdown_custom_timeout(self):
        service = MagicMock()
        service.shutdown = AsyncMock()

        resp = await handle_shutdown(self._mock_request(service, {"timeout_seconds": 10}))
        data = json.loads(resp.body)
        assert data["shutting_down"] is True

    @pytest.mark.asyncio
    async def test_shutdown_invalid_timeout(self):
        service = MagicMock()
        resp = await handle_shutdown(self._mock_request(service, {"timeout_seconds": "bad"}))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_shutdown_timeout_out_of_range(self):
        service = MagicMock()
        resp = await handle_shutdown(self._mock_request(service, {"timeout_seconds": 999}))
        assert resp.status_code == 400


# handle_sessions ─────────────────────────────────────────────────────


class TestHandleSessions:
    @staticmethod
    def _mock_request(service: MagicMock) -> MagicMock:
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        return req

    @pytest.mark.asyncio
    async def test_no_session_manager(self):
        service = MagicMock()
        mock_mcp = MagicMock()
        mock_mcp.session_manager = None

        with patch("argus_mcp.server.app.mcp_server", mock_mcp):
            resp = await handle_sessions(self._mock_request(service))

        data = json.loads(resp.body)
        assert data["active_sessions"] == 0
        assert data["sessions"] == []

    @pytest.mark.asyncio
    async def test_with_sessions(self):
        service = MagicMock()

        session_mgr = MagicMock()
        session_mgr.active_count = 2
        session_mgr.list_sessions.return_value = [
            {"id": "s1", "transport_type": "sse", "age_seconds": 10.0},
            {"id": "s2", "transport_type": "streamable_http", "age_seconds": 5.0},
        ]
        mock_mcp = MagicMock()
        mock_mcp.session_manager = session_mgr

        with patch("argus_mcp.server.app.mcp_server", mock_mcp):
            resp = await handle_sessions(self._mock_request(service))

        data = json.loads(resp.body)
        assert data["active_sessions"] == 2
        assert len(data["sessions"]) == 2
