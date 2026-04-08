"""Tests for containers REPL commands (Phase 3 Step 23)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.commands.containers import app  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

runner = CliRunner()

_PATCH_TARGET = "argus_cli.daemon_client.DaemonClient"


# Fixtures
def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.output_format = "rich"
    return cfg


def _wrap_app() -> typer.Typer:
    """Wrap the containers app in a parent so ctx.obj is set."""
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _main(ctx: typer.Context) -> None:
        ctx.obj = _make_config()

    parent.add_typer(app, name="containers")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# Helpers
_SAMPLE_CONTAINERS = [
    {
        "name": "argus-web",
        "id": "abc123def456",
        "status": "Up 2 hours",
        "image": "argus:latest",
        "state": "running",
        "uptime": "2h",
    },
    {
        "name": "argus-db",
        "id": "789xyz012345",
        "status": "Exited (0) 1 hour ago",
        "image": "postgres:16",
        "state": "exited",
        "uptime": "",
    },
]

_SAMPLE_INSPECT = {
    "name": "argus-web",
    "id": "abc123def456789",
    "image": "argus:latest",
    "state": "running",
    "config": {"env": ["FOO=bar"]},
}


# list
class TestListContainers:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.list_containers.return_value = _SAMPLE_CONTAINERS
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_daemon_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        mock_client = AsyncMock()
        mock_client.list_containers.side_effect = DaemonError("socket not found")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "list"])
            assert result.exit_code == 1


# inspect
class TestInspect:
    def test_inspect_success(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.inspect_container.return_value = _SAMPLE_INSPECT
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli_app, ["containers", "inspect", "argus-web", "--output", "json"]
            )
            assert result.exit_code == 0

    def test_inspect_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        mock_client = AsyncMock()
        mock_client.inspect_container.side_effect = DaemonError("not found", status_code=404)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "inspect", "no-such"])
            assert result.exit_code == 1


# logs
class TestLogs:
    def test_logs_no_follow(self, cli_app: typer.Typer) -> None:
        async def _fake_stream(*_a, **_kw):
            yield {"event": "log", "data": {"line": "INFO: server started"}}

        mock_client = AsyncMock()
        mock_client.stream_logs = _fake_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "logs", "argus-web"])
            assert result.exit_code == 0
            assert "server started" in result.output

    def test_logs_with_tail(self, cli_app: typer.Typer) -> None:
        async def _fake_stream(*_a, **_kw):
            yield {"event": "log", "data": {"line": "last line"}}

        mock_client = AsyncMock()
        mock_client.stream_logs = _fake_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "logs", "argus-web", "--tail", "10"])
            assert result.exit_code == 0

    def test_logs_daemon_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        async def _fail_stream(*_a, **_kw):
            raise DaemonError("connection refused")
            yield  # noqa: B901 — unreachable but makes it async generator  # pragma: no cover

        mock_client = AsyncMock()
        mock_client.stream_logs = _fail_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "logs", "argus-web"])
            assert result.exit_code == 1


# stats
class TestStats:
    def test_stats_snapshot(self, cli_app: typer.Typer) -> None:
        async def _fake_stream(*_a, **_kw):
            yield {
                "event": "stats",
                "data": {
                    "cpu_percent": 25.3,
                    "memory_usage": "128MB",
                    "memory_limit": "512MB",
                    "memory_percent": 25.0,
                    "net_rx": "1.2MB",
                    "net_tx": "0.5MB",
                    "pids": 12,
                },
            }

        mock_client = AsyncMock()
        mock_client.stream_stats = _fake_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli_app, ["containers", "stats", "argus-web", "--output", "json"]
            )
            assert result.exit_code == 0

    def test_stats_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        async def _fail_stream(*_a, **_kw):
            raise DaemonError("not found")
            yield  # noqa: B901  # pragma: no cover

        mock_client = AsyncMock()
        mock_client.stream_stats = _fail_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "stats", "argus-web"])
            assert result.exit_code == 1


# lifecycle (start, stop, restart, remove)
class TestLifecycle:
    def test_start_success(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.start_container.return_value = {"status": "started"}
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "start", "argus-web"])
            assert result.exit_code == 0
            assert "started" in result.output

    def test_stop_confirmed(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.stop_container.return_value = {"status": "stopped"}
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "stop", "argus-web", "--force"])
            assert result.exit_code == 0
            assert "stopped" in result.output

    def test_stop_aborted(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["containers", "stop", "argus-web"], input="n\n")
        assert result.exit_code != 0  # Abort

    def test_restart_force(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.restart_container.return_value = {"status": "restarted"}
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "restart", "argus-web", "--force"])
            assert result.exit_code == 0
            assert "restarted" in result.output

    def test_remove_force(self, cli_app: typer.Typer) -> None:
        mock_client = AsyncMock()
        mock_client.remove_container.return_value = {"status": "removed"}
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "remove", "argus-web", "--force"])
            assert result.exit_code == 0
            assert "removed" in result.output

    def test_remove_aborted(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["containers", "remove", "argus-web"], input="n\n")
        assert result.exit_code != 0  # Abort

    def test_start_error(self, cli_app: typer.Typer) -> None:
        from argus_cli.daemon_client import DaemonError

        mock_client = AsyncMock()
        mock_client.start_container.side_effect = DaemonError("already running")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            _PATCH_TARGET,
            return_value=mock_client,
        ):
            result = runner.invoke(cli_app, ["containers", "start", "argus-web"])
            assert result.exit_code == 1
