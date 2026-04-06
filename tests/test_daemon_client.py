"""Tests for the argusd daemon client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from argus_cli.daemon_client import (
    DaemonClient,
    DaemonError,
    default_socket_path,
)

# ── default_socket_path ───────────────────────────────────────────────


class TestDefaultSocketPath:
    def test_uses_xdg_runtime_dir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert default_socket_path() == "/run/user/1000/argusd.sock"

    def test_falls_back_to_tmpdir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        path = default_socket_path()
        assert path.endswith("argusd.sock")
        assert "tmp" in path.lower() or "temp" in path.lower()


# ── DaemonClient lifecycle ────────────────────────────────────────────


class TestDaemonClientLifecycle:
    def test_default_socket_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/42")
        client = DaemonClient()
        assert client.socket_path == "/run/user/42/argusd.sock"

    def test_custom_socket_path(self):
        client = DaemonClient(socket_path="/tmp/custom.sock")
        assert client.socket_path == "/tmp/custom.sock"

    def test_not_connected_initially(self):
        client = DaemonClient(socket_path="/tmp/test.sock")
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_creates_client(self):
        client = DaemonClient(socket_path="/tmp/test.sock")
        await client.connect()
        assert client.is_connected is True
        await client.close()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with DaemonClient(socket_path="/tmp/test.sock") as client:
            assert client.is_connected is True
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_double_connect_is_noop(self):
        client = DaemonClient(socket_path="/tmp/test.sock")
        await client.connect()
        first_client = client._client
        await client.connect()
        assert client._client is first_client
        await client.close()


# ── DaemonClient._request ────────────────────────────────────────────


def _make_client_with_mock(
    status_code: int = 200,
    json_data: dict[str, Any] | list[Any] | None = None,
    text: str = "",
) -> tuple[DaemonClient, AsyncMock]:
    """Create a DaemonClient with a mocked httpx.AsyncClient."""
    dc = DaemonClient(socket_path="/tmp/test.sock")
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data if json_data is not None else {}
    mock_response.text = text or json.dumps(json_data or {})

    mock_httpx = AsyncMock(spec=httpx.AsyncClient)
    mock_httpx.is_closed = False
    mock_httpx.request.return_value = mock_response
    dc._client = mock_httpx
    return dc, mock_httpx


class TestDaemonClientRequest:
    @pytest.mark.asyncio
    async def test_successful_get(self):
        dc, mock = _make_client_with_mock(
            json_data={"status": "ok", "docker": True},
        )
        result = await dc.health()
        assert result == {"status": "ok", "docker": True}
        mock.request.assert_called_once_with("GET", "/v1/health")

    @pytest.mark.asyncio
    async def test_error_response(self):
        dc, _ = _make_client_with_mock(
            status_code=404,
            json_data={"error": "container not found"},
        )
        with pytest.raises(DaemonError, match="container not found"):
            await dc.inspect_container("abc123")

    @pytest.mark.asyncio
    async def test_connection_error(self):
        dc = DaemonClient(socket_path="/tmp/test.sock")
        mock_httpx = AsyncMock(spec=httpx.AsyncClient)
        mock_httpx.is_closed = False
        mock_httpx.request.side_effect = httpx.ConnectError("Connection refused")
        dc._client = mock_httpx
        with pytest.raises(DaemonError, match="Cannot connect"):
            await dc.health()

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        dc = DaemonClient(socket_path="/tmp/test.sock")
        mock_httpx = AsyncMock(spec=httpx.AsyncClient)
        mock_httpx.is_closed = False
        mock_httpx.request.side_effect = httpx.TimeoutException("timed out")
        dc._client = mock_httpx
        with pytest.raises(DaemonError, match="Timeout"):
            await dc.health()

    @pytest.mark.asyncio
    async def test_not_connected_raises(self):
        dc = DaemonClient(socket_path="/tmp/test.sock")
        with pytest.raises(DaemonError, match="not connected"):
            await dc.health()


# ── Docker Container methods ──────────────────────────────────────────


class TestContainerMethods:
    @pytest.mark.asyncio
    async def test_list_containers(self):
        containers = [{"id": "abc", "name": "test", "status": "running"}]
        dc, mock = _make_client_with_mock(json_data=containers)
        result = await dc.list_containers()
        assert result == containers
        mock.request.assert_called_once_with("GET", "/v1/containers")

    @pytest.mark.asyncio
    async def test_inspect_container(self):
        dc, mock = _make_client_with_mock(
            json_data={"id": "abc", "name": "test"},
        )
        result = await dc.inspect_container("abc")
        assert result["id"] == "abc"
        mock.request.assert_called_once_with("GET", "/v1/containers/abc")

    @pytest.mark.asyncio
    async def test_start_container(self):
        dc, mock = _make_client_with_mock(json_data={"status": "started"})
        result = await dc.start_container("abc")
        assert result["status"] == "started"
        mock.request.assert_called_once_with("POST", "/v1/containers/abc/start")

    @pytest.mark.asyncio
    async def test_stop_container(self):
        dc, mock = _make_client_with_mock(json_data={"status": "stopped"})
        result = await dc.stop_container("abc")
        assert result["status"] == "stopped"
        mock.request.assert_called_once_with("POST", "/v1/containers/abc/stop")

    @pytest.mark.asyncio
    async def test_restart_container(self):
        dc, mock = _make_client_with_mock(json_data={"status": "restarted"})
        result = await dc.restart_container("abc")
        assert result["status"] == "restarted"
        mock.request.assert_called_once_with("POST", "/v1/containers/abc/restart")

    @pytest.mark.asyncio
    async def test_remove_container(self):
        dc, mock = _make_client_with_mock(json_data={"status": "removed"})
        result = await dc.remove_container("abc")
        assert result["status"] == "removed"
        mock.request.assert_called_once_with("POST", "/v1/containers/abc/remove")


# ── Kubernetes methods ────────────────────────────────────────────────


class TestKubernetesMethods:
    @pytest.mark.asyncio
    async def test_list_pods(self):
        pods = [{"name": "mypod", "namespace": "default", "status": "Running"}]
        dc, mock = _make_client_with_mock(json_data=pods)
        result = await dc.list_pods()
        assert result == pods
        mock.request.assert_called_once_with("GET", "/v1/pods")

    @pytest.mark.asyncio
    async def test_describe_pod(self):
        dc, mock = _make_client_with_mock(
            json_data={"name": "mypod", "namespace": "default"},
        )
        result = await dc.describe_pod("default", "mypod")
        assert result["name"] == "mypod"
        mock.request.assert_called_once_with("GET", "/v1/pods/default/mypod")

    @pytest.mark.asyncio
    async def test_delete_pod(self):
        dc, mock = _make_client_with_mock(json_data={"status": "deleted"})
        result = await dc.delete_pod("default", "mypod")
        assert result["status"] == "deleted"
        mock.request.assert_called_once_with("DELETE", "/v1/pods/default/mypod")

    @pytest.mark.asyncio
    async def test_pod_events(self):
        events = [{"type": "Normal", "reason": "Started"}]
        dc, mock = _make_client_with_mock(json_data=events)
        result = await dc.pod_events("default", "mypod")
        assert result == events
        mock.request.assert_called_once_with("GET", "/v1/pods/default/mypod/events")

    @pytest.mark.asyncio
    async def test_rollout_restart(self):
        dc, mock = _make_client_with_mock(json_data={"status": "restarting"})
        result = await dc.rollout_restart("default", "mydeployment")
        assert result["status"] == "restarting"
        mock.request.assert_called_once_with("POST", "/v1/deployments/default/mydeployment/restart")


# ── SSE streaming ─────────────────────────────────────────────────────


class _FakeSSE:
    """Mimics an httpx_sse ServerSentEvent."""

    def __init__(self, event: str, data: str, id: str = ""):
        self.event = event
        self.data = data
        self.id = id


class _FakeEventSource:
    """Mimics httpx_sse EventSource with async iteration."""

    def __init__(self, events: list[_FakeSSE]):
        self._events = events

    async def aiter_sse(self):
        for ev in self._events:
            yield ev

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object):
        pass


class TestSSEStreaming:
    @pytest.mark.asyncio
    async def test_stream_events(self):
        fake_events = [
            _FakeSSE("docker_event", json.dumps({"action": "start", "id": "abc"})),
            _FakeSSE("docker_event", json.dumps({"action": "stop", "id": "def"})),
        ]
        dc = DaemonClient(socket_path="/tmp/test.sock")
        mock_httpx = AsyncMock(spec=httpx.AsyncClient)
        mock_httpx.is_closed = False
        dc._client = mock_httpx

        with patch(
            "httpx_sse.aconnect_sse",
            return_value=_FakeEventSource(fake_events),
        ):
            collected = []
            async for event in dc.stream_events():
                collected.append(event)

        assert len(collected) == 2
        assert collected[0]["event"] == "docker_event"
        assert collected[0]["data"]["action"] == "start"

    @pytest.mark.asyncio
    async def test_stream_logs(self):
        fake_events = [
            _FakeSSE("log", json.dumps({"line": "hello world", "stream": "stdout"})),
        ]
        dc = DaemonClient(socket_path="/tmp/test.sock")
        mock_httpx = AsyncMock(spec=httpx.AsyncClient)
        mock_httpx.is_closed = False
        dc._client = mock_httpx

        with patch(
            "httpx_sse.aconnect_sse",
            return_value=_FakeEventSource(fake_events),
        ):
            collected = []
            async for event in dc.stream_logs("abc", tail="100", since="1h"):
                collected.append(event)

        assert len(collected) == 1
        assert collected[0]["data"]["line"] == "hello world"

    @pytest.mark.asyncio
    async def test_stream_stats(self):
        fake_events = [
            _FakeSSE("stats", json.dumps({"cpu_percent": 12.5, "mem_mb": 256})),
        ]
        dc = DaemonClient(socket_path="/tmp/test.sock")
        mock_httpx = AsyncMock(spec=httpx.AsyncClient)
        mock_httpx.is_closed = False
        dc._client = mock_httpx

        with patch(
            "httpx_sse.aconnect_sse",
            return_value=_FakeEventSource(fake_events),
        ):
            collected = []
            async for event in dc.stream_stats("abc"):
                collected.append(event)

        assert len(collected) == 1
        assert collected[0]["data"]["cpu_percent"] == 12.5

    @pytest.mark.asyncio
    async def test_stream_error_event_raises(self):
        fake_events = [
            _FakeSSE("error", json.dumps({"error": "container gone"})),
        ]
        dc = DaemonClient(socket_path="/tmp/test.sock")
        mock_httpx = AsyncMock(spec=httpx.AsyncClient)
        mock_httpx.is_closed = False
        dc._client = mock_httpx

        with patch(
            "httpx_sse.aconnect_sse",
            return_value=_FakeEventSource(fake_events),
        ):
            with pytest.raises(DaemonError, match="container gone"):
                async for _ in dc.stream_events():
                    pass

    @pytest.mark.asyncio
    async def test_stream_pod_logs(self):
        fake_events = [
            _FakeSSE("log", json.dumps({"line": "pod output"})),
        ]
        dc = DaemonClient(socket_path="/tmp/test.sock")
        mock_httpx = AsyncMock(spec=httpx.AsyncClient)
        mock_httpx.is_closed = False
        dc._client = mock_httpx

        with patch(
            "httpx_sse.aconnect_sse",
            return_value=_FakeEventSource(fake_events),
        ):
            collected = []
            async for event in dc.stream_pod_logs("default", "mypod", container="main", tail="50"):
                collected.append(event)

        assert len(collected) == 1
        assert collected[0]["data"]["line"] == "pod output"
