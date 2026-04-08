"""Tests for backends CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.backends import app  # noqa: E402
from typer.testing import CliRunner  # noqa: E402


def make_cli_config():
    """Create a mock CLI config for ArgusClient-based commands."""
    cfg = MagicMock()
    cfg.output_format = "rich"
    cfg.server_url = "http://localhost:8080"
    cfg.token = "test-token"
    cfg.no_color = False
    cfg.theme = "default"
    cfg.show_toolbar = True
    cfg.vi_mode = False
    cfg.poll_interval = 2.0
    cfg.history_limit = 100
    cfg.config_file = "/tmp/argus-config.yaml"
    return cfg


runner = CliRunner()

_PATCH = "argus_cli.client.ArgusClient"

_SAMPLE_BACKENDS = {
    "backends": [
        {
            "name": "test-be",
            "type": "stdio",
            "group": "default",
            "phase": "running",
            "state": "connected",
            "capabilities": {"tools": 5, "resources": 2, "prompts": 1},
            "health": {"status": "healthy", "latency_ms": 12, "last_check": "2024-01-01T00:00:00Z"},
        },
        {
            "name": "sse-be",
            "type": "sse",
            "group": "default",
            "phase": "stopped",
            "state": "disconnected",
            "capabilities": {"tools": 0, "resources": 0, "prompts": 0},
            "health": {"status": "unhealthy", "latency_ms": None, "last_check": None},
        },
    ]
}


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="backends")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


def _mock_client(**overrides) -> MagicMock:
    mc = MagicMock()
    mc.__enter__ = MagicMock(return_value=mc)
    mc.__exit__ = MagicMock(return_value=False)
    for k, v in overrides.items():
        setattr(mc, k, v)
    return mc


# list
class TestListBackends:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.return_value = _SAMPLE_BACKENDS
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "list"])
            assert result.exit_code == 1


# inspect
# inspect calls client.backends() and finds by name in the list


class TestInspectBackend:
    def test_inspect_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.return_value = _SAMPLE_BACKENDS
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "inspect", "test-be", "--output", "json"])
            assert result.exit_code == 0

    def test_inspect_not_found(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.return_value = _SAMPLE_BACKENDS
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "inspect", "missing"])
            assert result.exit_code == 1

    def test_inspect_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.side_effect = ArgusClientError(404, "not_found", "no such backend")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "inspect", "missing"])
            assert result.exit_code == 1


# reconnect
# reconnect uses client.reconnect(name) and checks result.get("reconnected")
# Also uses console.status() context manager


class TestReconnect:
    def test_reconnect_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.reconnect.return_value = {"reconnected": True}
        mock_console = MagicMock()
        mock_console.status.return_value.__enter__ = MagicMock()
        mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(_PATCH, return_value=mc),
            patch("argus_cli.output.get_console", return_value=mock_console),
        ):
            result = runner.invoke(cli_app, ["backends", "reconnect", "test-be"])
            assert result.exit_code == 0

    def test_reconnect_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.reconnect.side_effect = ArgusClientError(500, "error", "failed")
        mock_console = MagicMock()
        mock_console.status.return_value.__enter__ = MagicMock()
        mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(_PATCH, return_value=mc),
            patch("argus_cli.output.get_console", return_value=mock_console),
        ):
            result = runner.invoke(cli_app, ["backends", "reconnect", "test-be"])
            assert result.exit_code == 1


# reconnect-all
# reconnect_all calls client.backends() first, then iterates and calls
# client.reconnect(name) for each backend


class TestReconnectAll:
    def test_reconnect_all_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.return_value = _SAMPLE_BACKENDS
        mc.reconnect.return_value = {"reconnected": True}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "reconnect-all"])
            assert result.exit_code == 0

    def test_reconnect_all_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "reconnect-all"])
            assert result.exit_code == 1


# health
# health calls client.backends() and extracts health info per backend


class TestBackendHealth:
    def test_health_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.return_value = _SAMPLE_BACKENDS
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "health", "--output", "json"])
            assert result.exit_code == 0

    def test_health_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.backends.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "health"])
            assert result.exit_code == 1


# groups
# groups calls client.groups()


class TestBackendGroups:
    def test_groups_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.groups.return_value = {"groups": [{"name": "default", "backends": ["be-1"]}]}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "groups", "--output", "json"])
            assert result.exit_code == 0

    def test_groups_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.groups.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "groups"])
            assert result.exit_code == 1


# sessions
# sessions calls client.sessions()


class TestBackendSessions:
    def test_sessions_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.sessions.return_value = {
            "sessions": [
                {
                    "id": "s1",
                    "transport_type": "stdio",
                    "tool_count": 5,
                    "age_seconds": 120,
                    "idle_seconds": 10,
                    "expired": False,
                }
            ],
            "active_sessions": 1,
        }
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "sessions", "--output", "json"])
            assert result.exit_code == 0

    def test_sessions_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.sessions.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "sessions"])
            assert result.exit_code == 1


# versions
# versions calls client.status() (not client.versions())


class TestBackendVersions:
    def test_versions_success(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.status.return_value = {
            "service": {"name": "argus-mcp", "version": "1.0.0"},
            "transport": {},
        }
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "versions", "--output", "json"])
            assert result.exit_code == 0

    def test_versions_error(self, cli_app: typer.Typer) -> None:
        mc = _mock_client()
        mc.status.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["backends", "versions"])
            assert result.exit_code == 1
