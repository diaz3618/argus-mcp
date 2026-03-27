"""Tests for ``argus_mcp.runtime.service`` — ArgusService lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.runtime.models import ServiceState, is_valid_transition
from argus_mcp.runtime.service import ArgusService, _InvalidStateTransition

# Helpers


def _dummy_config() -> Dict[str, Any]:
    """Return a minimal backends dict for testing."""
    return {
        "backend-a": {"type": "stdio", "command": "echo"},
        "backend-b": {"type": "sse", "url": "http://localhost:8080/sse"},
    }


# _InvalidStateTransition


class TestInvalidStateTransition:
    def test_message_format(self) -> None:
        exc = _InvalidStateTransition(ServiceState.PENDING, ServiceState.RUNNING)
        assert "pending" in str(exc)
        assert "running" in str(exc)

    def test_attributes(self) -> None:
        exc = _InvalidStateTransition(ServiceState.RUNNING, ServiceState.PENDING)
        assert exc.current == ServiceState.RUNNING
        assert exc.target == ServiceState.PENDING


# ArgusService.__init__


class TestInit:
    def test_initial_state_pending(self) -> None:
        svc = ArgusService()
        assert svc.state == ServiceState.PENDING

    def test_properties_initial_values(self) -> None:
        svc = ArgusService()
        assert svc.started_at is None
        assert svc.error_message is None
        assert svc.backends_total == 0
        assert svc.backends_connected == 0
        assert svc.tools == []
        assert svc.resources == []
        assert svc.prompts == []
        assert svc.config_data is None
        assert svc.full_config is None
        assert svc.is_running is False
        assert svc.health_checker is None
        assert svc.group_manager is None

    def test_manager_and_registry_created(self) -> None:
        svc = ArgusService()
        assert svc.manager is not None
        assert svc.registry is not None


# _transition


class TestTransition:
    def test_valid_transition(self) -> None:
        svc = ArgusService()
        assert svc.state == ServiceState.PENDING
        svc._transition(ServiceState.STARTING)
        assert svc.state == ServiceState.STARTING

    def test_invalid_transition_raises(self) -> None:
        svc = ArgusService()
        with pytest.raises(_InvalidStateTransition):
            svc._transition(ServiceState.RUNNING)

    def test_event_emitted_on_transition(self) -> None:
        svc = ArgusService()
        svc._transition(ServiceState.STARTING)
        events = svc.get_events()
        status_events = [e for e in events if e["stage"] == "status"]
        assert len(status_events) >= 1
        assert "starting" in status_events[-1]["message"]


# _build_registry


class TestBuildRegistry:
    def test_returns_default_when_no_config_path(self) -> None:
        svc = ArgusService()
        reg = svc._build_registry()
        assert reg is not None

    @patch("argus_mcp.runtime.service.load_argus_config")
    def test_returns_default_on_config_error(self, mock_load: MagicMock) -> None:
        mock_load.side_effect = OSError("missing")
        svc = ArgusService()
        svc._config_path = "/fake/path.yaml"
        reg = svc._build_registry()
        assert reg is not None

    @patch("argus_mcp.runtime.service.load_argus_config")
    @patch("argus_mcp.runtime.service.create_strategy")
    def test_uses_config_strategy(self, mock_strategy: MagicMock, mock_load: MagicMock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.conflict_resolution.strategy = "first-wins"
        mock_cfg.conflict_resolution.separator = "_"
        mock_cfg.conflict_resolution.order = None
        mock_cfg.backends = {}
        mock_load.return_value = mock_cfg
        mock_strategy.return_value = MagicMock()

        svc = ArgusService()
        svc._config_path = "/fake/path.yaml"
        reg = svc._build_registry()
        assert reg is not None
        mock_strategy.assert_called_once()


# _build_group_manager


class TestBuildGroupManager:
    @patch("argus_mcp.runtime.service.load_argus_config")
    def test_builds_from_config(self, mock_load: MagicMock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.backends = {}
        mock_load.return_value = mock_cfg

        svc = ArgusService()
        svc._config_path = "/fake/path.yaml"
        gm = svc._build_group_manager(_dummy_config())
        assert gm is not None

    @patch("argus_mcp.runtime.service.load_argus_config")
    def test_fallback_on_error(self, mock_load: MagicMock) -> None:
        mock_load.side_effect = OSError("fail")
        svc = ArgusService()
        svc._config_path = "/fake/path.yaml"
        gm = svc._build_group_manager(_dummy_config())
        assert gm is not None

    def test_returns_empty_when_no_config_path(self) -> None:
        svc = ArgusService()
        gm = svc._build_group_manager(_dummy_config())
        assert gm is not None


# start


class TestStart:
    @pytest.mark.asyncio
    @patch("argus_mcp.runtime.service.load_and_validate_config")
    @patch("argus_mcp.runtime.service.load_argus_config")
    async def test_start_full_success(
        self, mock_full_cfg: MagicMock, mock_validate: MagicMock
    ) -> None:
        config = _dummy_config()
        mock_validate.return_value = config
        mock_full_cfg.side_effect = OSError("skip full cfg")

        svc = ArgusService()
        svc._manager = MagicMock()
        svc._manager.start_all = AsyncMock()
        svc._manager.get_all_sessions.return_value = {"backend-a": MagicMock()}
        svc._manager.get_active_session_count.return_value = 1

        svc._registry = MagicMock()
        svc._registry.discover_and_register = AsyncMock()
        svc._registry.get_aggregated_tools.return_value = [MagicMock(name="tool1")]
        svc._registry.get_aggregated_resources.return_value = []
        svc._registry.get_aggregated_prompts.return_value = []

        with patch.object(svc, "_build_registry", return_value=svc._registry):
            await svc.start(config_path="/fake/config.yaml")

        assert svc.state == ServiceState.RUNNING
        assert svc.is_running is True
        assert svc.started_at is not None
        assert svc.backends_total == 2
        assert svc.backends_connected == 1
        assert len(svc.tools) == 1

    @pytest.mark.asyncio
    @patch("argus_mcp.runtime.service.load_argus_config")
    @patch("argus_mcp.runtime.service.load_and_validate_config")
    async def test_start_no_backends_raises(
        self, mock_validate: MagicMock, mock_full: MagicMock
    ) -> None:
        mock_validate.return_value = _dummy_config()
        mock_full.side_effect = OSError("skip")

        svc = ArgusService()
        svc._manager = MagicMock()
        svc._manager.start_all = AsyncMock()
        svc._manager.get_all_sessions.return_value = {}

        with patch.object(svc, "_build_registry", return_value=MagicMock()):
            with pytest.raises(Exception, match="Unable to connect"):
                await svc.start(config_path="/fake/config.yaml")

        assert svc.state == ServiceState.ERROR

    @pytest.mark.asyncio
    @patch("argus_mcp.runtime.service.load_and_validate_config")
    async def test_start_config_error_transitions_to_error(self, mock_validate: MagicMock) -> None:
        mock_validate.side_effect = OSError("file not found")

        svc = ArgusService()
        with pytest.raises(OSError):
            await svc.start(config_path="/fake/config.yaml")

        assert svc.state == ServiceState.ERROR
        assert svc.error_message is not None
        assert "OSError" in svc.error_message

    @pytest.mark.asyncio
    async def test_start_from_wrong_state_raises(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        with pytest.raises(_InvalidStateTransition):
            await svc.start(config_path="/fake/config.yaml")

    @pytest.mark.asyncio
    @patch("argus_mcp.runtime.service.load_and_validate_config")
    @patch("argus_mcp.runtime.service.load_argus_config")
    async def test_start_with_progress_callback(
        self, mock_full: MagicMock, mock_validate: MagicMock
    ) -> None:
        mock_validate.return_value = {"only-backend": {"type": "stdio"}}
        mock_full.side_effect = OSError("skip")

        svc = ArgusService()
        svc._manager = MagicMock()
        svc._manager.start_all = AsyncMock()
        svc._manager.get_all_sessions.return_value = {"only-backend": MagicMock()}
        svc._manager.get_active_session_count.return_value = 1

        svc._registry = MagicMock()
        svc._registry.discover_and_register = AsyncMock()
        svc._registry.get_aggregated_tools.return_value = []
        svc._registry.get_aggregated_resources.return_value = []
        svc._registry.get_aggregated_prompts.return_value = []

        cb = MagicMock()
        with patch.object(svc, "_build_registry", return_value=svc._registry):
            await svc.start(config_path="/fake/config.yaml", progress_callback=cb)

        assert svc.state == ServiceState.RUNNING


# stop


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_from_running(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._manager = MagicMock()
        svc._manager.stop_all = AsyncMock()

        await svc.stop()
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_from_error(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.ERROR
        svc._manager = MagicMock()
        svc._manager.stop_all = AsyncMock()

        await svc.stop()
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_from_pending_is_noop(self) -> None:
        svc = ArgusService()
        assert svc.state == ServiceState.PENDING
        await svc.stop()
        assert svc.state == ServiceState.PENDING

    @pytest.mark.asyncio
    async def test_stop_from_stopped_is_noop(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.STOPPED
        await svc.stop()
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_from_starting_forces_error_then_stopping(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.STARTING
        svc._manager = MagicMock()
        svc._manager.stop_all = AsyncMock()

        await svc.stop()
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_duplicate_call_ignored(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.STOPPING
        await svc.stop()
        assert svc.state == ServiceState.STOPPING

    @pytest.mark.asyncio
    async def test_stop_with_config_watcher(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._manager = MagicMock()
        svc._manager.stop_all = AsyncMock()

        watcher = MagicMock()
        watcher.stop = AsyncMock()
        svc._config_watcher = watcher

        checker = MagicMock()
        checker.stop = AsyncMock()
        svc._health_checker = checker

        await svc.stop()
        assert svc.state == ServiceState.STOPPED
        watcher.stop.assert_awaited_once()
        checker.stop.assert_awaited_once()
        assert svc._config_watcher is None
        assert svc._health_checker is None

    @pytest.mark.asyncio
    async def test_stop_manager_runtime_error_handled(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._manager = MagicMock()
        svc._manager.stop_all = AsyncMock(side_effect=RuntimeError("cancel scope cross-task"))

        await svc.stop()
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_stop_manager_generic_error(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._manager = MagicMock()
        svc._manager.stop_all = AsyncMock(side_effect=Exception("kaboom"))

        await svc.stop()
        assert svc.state == ServiceState.ERROR
        assert "kaboom" in (svc.error_message or "")


# reload


class TestReload:
    @pytest.mark.asyncio
    async def test_reload_not_running(self) -> None:
        svc = ArgusService()
        result = await svc.reload()
        assert result["reloaded"] is False
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_reload_no_config_path(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_path = None
        result = await svc.reload()
        assert result["reloaded"] is False
        assert "No config path" in result["errors"][0]

    @pytest.mark.asyncio
    @patch("argus_mcp.runtime.service.load_and_validate_config")
    @patch("argus_mcp.runtime.service.compute_diff")
    async def test_reload_success(self, mock_diff: MagicMock, mock_validate: MagicMock) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_path = "/fake/config.yaml"
        svc._config_data = {"old-backend": {"type": "stdio"}}

        new_config = {"new-backend": {"type": "sse"}}
        mock_validate.return_value = new_config

        mock_diff_obj = MagicMock()
        mock_diff_obj.added = ["new-backend"]
        mock_diff_obj.removed = ["old-backend"]
        mock_diff_obj.changed = []
        mock_diff_obj.summary.return_value = "1 added, 1 removed"
        mock_diff.return_value = mock_diff_obj

        svc._manager = MagicMock()
        svc._manager.get_active_session_count.return_value = 1
        svc._manager.get_all_sessions.return_value = {"new-backend": MagicMock()}
        svc._manager.disconnect_one = AsyncMock()

        mock_connect = AsyncMock(return_value=True)
        svc._connect_backend = mock_connect  # type: ignore[method-assign]
        svc._disconnect_backend = AsyncMock()  # type: ignore[method-assign]

        svc._registry = MagicMock()
        svc._registry.discover_and_register = AsyncMock()
        svc._registry.get_aggregated_tools.return_value = []
        svc._registry.get_aggregated_resources.return_value = []
        svc._registry.get_aggregated_prompts.return_value = []

        with patch.object(svc, "_build_registry", return_value=svc._registry):
            result = await svc.reload()

        assert result["reloaded"] is True
        assert "new-backend" in result["backends_added"]
        assert "old-backend" in result["backends_removed"]

    @pytest.mark.asyncio
    @patch("argus_mcp.runtime.service.load_and_validate_config")
    async def test_reload_config_error(self, mock_validate: MagicMock) -> None:
        mock_validate.side_effect = OSError("cannot read")

        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_path = "/fake/config.yaml"

        result = await svc.reload()
        assert result["reloaded"] is False
        assert any("Config reload failed" in e for e in result["errors"])


# reconnect_backend


class TestReconnectBackend:
    @pytest.mark.asyncio
    async def test_not_running(self) -> None:
        svc = ArgusService()
        result = await svc.reconnect_backend("x")
        assert result["reconnected"] is False
        assert "Cannot reconnect" in result["error"]

    @pytest.mark.asyncio
    async def test_backend_not_in_config(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_data = {"other": {}}
        result = await svc.reconnect_backend("missing")
        assert result["reconnected"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_reconnect_success(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_data = {"my-backend": {"type": "stdio"}}

        svc._disconnect_backend = AsyncMock()  # type: ignore[method-assign]
        svc._connect_backend = AsyncMock(return_value=True)  # type: ignore[method-assign]

        svc._manager = MagicMock()
        svc._manager.get_all_sessions.return_value = {"my-backend": MagicMock()}
        svc._manager.get_active_session_count.return_value = 1

        svc._registry = MagicMock()
        svc._registry.discover_and_register = AsyncMock()
        svc._registry.get_aggregated_tools.return_value = []
        svc._registry.get_aggregated_resources.return_value = []
        svc._registry.get_aggregated_prompts.return_value = []

        with patch.object(svc, "_build_registry", return_value=svc._registry):
            result = await svc.reconnect_backend("my-backend")

        assert result["reconnected"] is True
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_reconnect_failure(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_data = {"fail-backend": {"type": "stdio"}}

        svc._disconnect_backend = AsyncMock()  # type: ignore[method-assign]
        svc._connect_backend = AsyncMock(return_value=False)  # type: ignore[method-assign]

        svc._manager = MagicMock()
        svc._manager.get_active_session_count.return_value = 0

        result = await svc.reconnect_backend("fail-backend")
        assert result["reconnected"] is False
        assert "Failed" in result["error"]

    @pytest.mark.asyncio
    async def test_reconnect_exception(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_data = {"err-backend": {"type": "stdio"}}

        svc._disconnect_backend = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom")
        )

        result = await svc.reconnect_backend("err-backend")
        assert result["reconnected"] is False
        assert "RuntimeError" in result["error"]


# shutdown


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_delegates_to_stop(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._manager = MagicMock()
        svc._manager.stop_all = AsyncMock()

        await svc.shutdown(timeout_seconds=5)
        assert svc.state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_shutdown_timeout(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING

        async def slow_stop() -> None:
            await asyncio.sleep(10)

        svc.stop = slow_stop  # type: ignore[method-assign]

        await svc.shutdown(timeout_seconds=0)
        assert svc.state == ServiceState.ERROR
        assert "timed out" in (svc.error_message or "")


# _disconnect_backend / _connect_backend


class TestBackendHelpers:
    @pytest.mark.asyncio
    async def test_disconnect_existing(self) -> None:
        svc = ArgusService()
        svc._manager = MagicMock()
        svc._manager.get_session.return_value = MagicMock()
        svc._manager.disconnect_one = AsyncMock()

        await svc._disconnect_backend("test-be")
        svc._manager.disconnect_one.assert_awaited_once_with("test-be")

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent(self) -> None:
        svc = ArgusService()
        svc._manager = MagicMock()
        svc._manager.get_session.return_value = None

        await svc._disconnect_backend("ghost")
        svc._manager.disconnect_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_success(self) -> None:
        svc = ArgusService()
        svc._manager = MagicMock()
        svc._manager._start_backend_svr = AsyncMock(return_value=True)

        result = await svc._connect_backend("be", {"type": "stdio"})
        assert result is True

    @pytest.mark.asyncio
    async def test_connect_failure(self) -> None:
        svc = ArgusService()
        svc._manager = MagicMock()
        svc._manager._start_backend_svr = AsyncMock(side_effect=RuntimeError("fail"))

        result = await svc._connect_backend("be", {"type": "stdio"})
        assert result is False


# get_status


class TestGetStatus:
    def test_status_snapshot(self) -> None:
        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        svc._config_path = "/test/config.yaml"
        svc._config_data = {"be1": {"type": "stdio"}}
        svc._backends_total = 1
        svc._backends_connected = 1

        mock_tool = MagicMock()
        mock_tool.name = "tool1"
        svc._tools = [mock_tool]
        svc._resources = []
        svc._prompts = []

        svc._manager = MagicMock()
        svc._manager.get_all_sessions.return_value = {"be1": MagicMock()}

        svc._registry = MagicMock()
        svc._registry.get_route_map.return_value = {}

        status = svc.get_status()
        assert status.state == ServiceState.RUNNING
        assert status.backends_total == 1
        assert status.capabilities.tools_count == 1
        assert "tool1" in status.capabilities.tool_names

    def test_status_with_no_config(self) -> None:
        svc = ArgusService()
        svc._registry = MagicMock()
        svc._registry.get_route_map.return_value = {}
        status = svc.get_status()
        assert status.state == ServiceState.PENDING
        assert status.backends == []


# _on_health_change


class TestOnHealthChange:
    def test_emits_warning_on_unhealthy(self) -> None:
        svc = ArgusService()
        old = MagicMock(value="healthy")
        new = MagicMock(value="unhealthy")

        svc._on_health_change("be1", old, new)
        events = svc.get_events(severity="warning")
        assert len(events) >= 1
        assert "be1" in events[-1]["message"]

    def test_emits_info_on_healthy(self) -> None:
        svc = ArgusService()
        old = MagicMock(value="unhealthy")
        new = MagicMock(value="healthy")

        svc._on_health_change("be1", old, new)
        events = svc.get_events(severity="info")
        assert any("be1" in e["message"] for e in events)


# Event system


class TestEventSystem:
    def test_emit_event_basic(self) -> None:
        svc = ArgusService()
        event = svc.emit_event("test_stage", "hello")
        assert event["stage"] == "test_stage"
        assert event["message"] == "hello"
        assert event["severity"] == "info"
        assert event["id"].startswith("evt-")

    def test_emit_event_with_details(self) -> None:
        svc = ArgusService()
        event = svc.emit_event(
            "deploy",
            "deploying",
            severity="warning",
            backend="be1",
            details={"key": "val"},
        )
        assert event["severity"] == "warning"
        assert event["backend"] == "be1"
        assert event["details"]["key"] == "val"

    def test_get_events_default(self) -> None:
        svc = ArgusService()
        for i in range(5):
            svc.emit_event("s", f"msg-{i}")
        events = svc.get_events()
        assert len(events) == 5

    def test_get_events_limit(self) -> None:
        svc = ArgusService()
        for i in range(10):
            svc.emit_event("s", f"msg-{i}")
        events = svc.get_events(limit=3)
        assert len(events) == 3

    def test_get_events_filter_severity(self) -> None:
        svc = ArgusService()
        svc.emit_event("s", "info-msg", severity="info")
        svc.emit_event("s", "warn-msg", severity="warning")
        events = svc.get_events(severity="warning")
        assert len(events) == 1
        assert events[0]["message"] == "warn-msg"

    def test_get_events_since_filter(self) -> None:
        svc = ArgusService()
        svc.emit_event("s", "old-msg")
        # Use a future timestamp to filter out everything
        events = svc.get_events(since="9999-01-01T00:00:00+00:00")
        assert len(events) == 0

    def test_subscribe_unsubscribe(self) -> None:
        svc = ArgusService()
        queue = svc.subscribe()
        assert queue is not None
        assert len(svc._event_subscribers) == 1

        svc.unsubscribe(queue)
        assert len(svc._event_subscribers) == 0

    def test_unsubscribe_nonexistent(self) -> None:
        svc = ArgusService()
        fake_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        svc.unsubscribe(fake_queue)  # should not raise

    def test_emit_pushes_to_subscriber(self) -> None:
        svc = ArgusService()
        queue = svc.subscribe()
        svc.emit_event("x", "pushed")
        assert not queue.empty()
        event = queue.get_nowait()
        assert event["message"] == "pushed"

    def test_emit_drops_on_full_queue(self) -> None:
        svc = ArgusService()
        small_q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=1)
        svc._event_subscribers.append(small_q)

        svc.emit_event("a", "first")
        svc.emit_event("b", "second")  # should be silently dropped
        assert small_q.qsize() == 1


# wait_until_ready


class TestWaitUntilReady:
    @pytest.mark.asyncio
    async def test_already_ready(self) -> None:
        svc = ArgusService()
        svc._ready_event.set()
        result = await svc.wait_until_ready(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        svc = ArgusService()
        result = await svc.wait_until_ready(timeout=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_becomes_ready(self) -> None:
        svc = ArgusService()

        async def set_ready() -> None:
            await asyncio.sleep(0.01)
            svc._ready_event.set()

        asyncio.get_event_loop().create_task(set_ready())
        result = await svc.wait_until_ready(timeout=2.0)
        assert result is True


# is_valid_transition (model-level)


class TestIsValidTransition:
    def test_pending_to_starting(self) -> None:
        assert is_valid_transition(ServiceState.PENDING, ServiceState.STARTING) is True

    def test_starting_to_running(self) -> None:
        assert is_valid_transition(ServiceState.STARTING, ServiceState.RUNNING) is True

    def test_running_to_stopping(self) -> None:
        assert is_valid_transition(ServiceState.RUNNING, ServiceState.STOPPING) is True

    def test_starting_and_stopping_can_error(self) -> None:
        assert is_valid_transition(ServiceState.STARTING, ServiceState.ERROR) is True
        assert is_valid_transition(ServiceState.STOPPING, ServiceState.ERROR) is True

    def test_pending_cannot_error(self) -> None:
        assert is_valid_transition(ServiceState.PENDING, ServiceState.ERROR) is False

    def test_invalid_pending_to_running(self) -> None:
        assert is_valid_transition(ServiceState.PENDING, ServiceState.RUNNING) is False
