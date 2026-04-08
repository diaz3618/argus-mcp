"""Tests for pods REPL commands (Phase 3 Step 24)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.commands.pods import app  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

runner = CliRunner()

_PATCH_TARGET = "argus_cli.daemon_client.DaemonClient"


# Fixtures
def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.output_format = "rich"
    return cfg


def _wrap_app() -> typer.Typer:
    """Wrap the pods app in a parent so ctx.obj is set."""
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _main(ctx: typer.Context) -> None:
        ctx.obj = _make_config()

    parent.add_typer(app, name="pods")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# Sample data
_SAMPLE_PODS = [
    {
        "name": "argus-server-abc12",
        "namespace": "argus",
        "status": "Running",
        "node": "node-1",
        "ip": "10.42.0.5",
        "restarts": 0,
        "age": "3d",
    },
    {
        "name": "argus-worker-xyz99",
        "namespace": "argus",
        "status": "Pending",
        "node": "",
        "ip": "",
        "restarts": 2,
        "age": "1h",
    },
]

_SAMPLE_DESCRIBE = {
    "name": "argus-server-abc12",
    "namespace": "argus",
    "status": "Running",
    "node": "node-1",
    "ip": "10.42.0.5",
    "containers": [{"name": "argus", "image": "argus:latest"}],
}

_SAMPLE_EVENTS = [
    {
        "type": "Normal",
        "reason": "Scheduled",
        "message": "Successfully assigned argus/argus-server-abc12 to node-1",
        "age": "3d",
        "count": 1,
    },
    {
        "type": "Warning",
        "reason": "BackOff",
        "message": "Back-off restarting failed container",
        "age": "1h",
        "count": 5,
    },
]


# List
class TestListPods:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.list_pods.return_value = _SAMPLE_PODS
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "list"])

        assert result.exit_code == 0
        assert "argus-server-abc12" in result.output
        mock_client.list_pods.assert_awaited_once()

    def test_list_daemon_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        mock_client = AsyncMock()
        mock_client.list_pods.side_effect = DaemonError("connection refused", status_code=500)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "list"])

        assert result.exit_code == 1


# Describe
class TestDescribe:
    def test_describe_success(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.describe_pod.return_value = _SAMPLE_DESCRIBE
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "describe", "argus/argus-server-abc12"])

        assert result.exit_code == 0
        mock_client.describe_pod.assert_awaited_once_with("argus", "argus-server-abc12")

    def test_describe_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        mock_client = AsyncMock()
        mock_client.describe_pod.side_effect = DaemonError("not found", status_code=404)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "describe", "default/missing"])

        assert result.exit_code == 1

    def test_describe_default_namespace(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.describe_pod.return_value = _SAMPLE_DESCRIBE
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "describe", "my-pod"])

        assert result.exit_code == 0
        mock_client.describe_pod.assert_awaited_once_with("default", "my-pod")


# Logs
class TestLogs:
    def test_logs_no_follow(self, cli_app: typer.Typer) -> None:
        async def _fake_stream(*_args, **_kwargs):
            yield {"data": {"line": "INFO: server started", "stream": "stdout"}}

        mock_client = AsyncMock()
        mock_client.stream_pod_logs = _fake_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "logs", "argus/argus-server-abc12"])

        assert result.exit_code == 0

    def test_logs_daemon_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        async def _fail_stream(*_args, **_kwargs):
            raise DaemonError("stream error", status_code=500)
            yield  # noqa: RET503 — make it a generator

        mock_client = AsyncMock()
        mock_client.stream_pod_logs = _fail_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "logs", "argus/argus-server-abc12"])

        assert result.exit_code == 1


# Events
class TestEvents:
    def test_events_success(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.pod_events.return_value = _SAMPLE_EVENTS
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "events", "argus/argus-server-abc12"])

        assert result.exit_code == 0
        mock_client.pod_events.assert_awaited_once_with("argus", "argus-server-abc12")

    def test_events_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        mock_client = AsyncMock()
        mock_client.pod_events.side_effect = DaemonError("not found", status_code=404)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(cli_app, ["pods", "events", "argus/argus-server-abc12"])

        assert result.exit_code == 1


# Lifecycle
class TestLifecycle:
    def test_delete_confirmed(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.delete_pod.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["pods", "delete", "argus/argus-server-abc12"], input="y\n"
            )

        assert result.exit_code == 0
        mock_client.delete_pod.assert_awaited_once_with("argus", "argus-server-abc12")

    def test_delete_aborted(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["pods", "delete", "argus/argus-server-abc12"], input="n\n"
            )

        assert result.exit_code != 0
        mock_client.delete_pod.assert_not_awaited()

    def test_delete_force(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.delete_pod.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["pods", "delete", "--force", "argus/argus-server-abc12"]
            )

        assert result.exit_code == 0
        mock_client.delete_pod.assert_awaited_once()

    def test_delete_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        mock_client = AsyncMock()
        mock_client.delete_pod.side_effect = DaemonError("forbidden", status_code=500)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["pods", "delete", "--force", "argus/my-pod"], input="y\n"
            )

        assert result.exit_code == 1

    def test_rollout_restart_confirmed(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.rollout_restart.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["pods", "rollout-restart", "argus/my-deploy"], input="y\n"
            )

        assert result.exit_code == 0
        mock_client.rollout_restart.assert_awaited_once_with("argus", "my-deploy")

    def test_rollout_restart_aborted(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["pods", "rollout-restart", "argus/my-deploy"], input="n\n"
            )

        assert result.exit_code != 0

    def test_rollout_restart_force(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.rollout_restart.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_PATCH_TARGET, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["pods", "rollout-restart", "--force", "argus/my-deploy"]
            )

        assert result.exit_code == 0
        mock_client.rollout_restart.assert_awaited_once()
