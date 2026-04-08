"""Tests for health CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.health import app  # noqa: E402
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


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="health")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# status
class TestStatus:
    def test_status_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.health.return_value = {
            "status": "healthy",
            "uptime_seconds": 8100,
            "version": "0.8.2",
            "backends": {"total": 3, "connected": 3, "healthy": 3},
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "status", "--output", "json"])
            assert result.exit_code == 0

    def test_status_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.health.side_effect = ArgusClientError(500, "error", "server down")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "status"])
            assert result.exit_code == 1


# sessions
class TestSessions:
    def test_sessions_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.sessions.return_value = {
            "sessions": [
                {
                    "id": "sess-1",
                    "transport_type": "sse",
                    "tool_count": 5,
                    "age_seconds": 3600,
                    "idle_seconds": 120,
                    "expired": False,
                }
            ]
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "sessions", "--output", "json"])
            assert result.exit_code == 0

    def test_sessions_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.sessions.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "sessions"])
            assert result.exit_code == 1


# versions
class TestVersions:
    def test_versions_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.return_value = {
            "service": {
                "name": "argus-mcp",
                "version": "1.0.0",
                "state": "running",
                "uptime_seconds": 3600,
            },
            "transport": {
                "sse_url": "http://localhost:8080/sse",
                "streamable_http_url": "http://localhost:8080/mcp",
            },
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "versions", "--output", "json"])
            assert result.exit_code == 0

    def test_versions_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "versions"])
            assert result.exit_code == 1


# groups
class TestGroups:
    def test_groups_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.groups.return_value = {
            "groups": [{"name": "default", "backends": ["be-1", "be-2"]}]
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "groups", "--output", "json"])
            assert result.exit_code == 0

    def test_groups_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.groups.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["health", "groups"])
            assert result.exit_code == 1
