"""Tests for server lifecycle CLI commands."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.server import app  # noqa: E402
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

    parent.add_typer(app, name="server")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# start
class TestStart:
    @patch("argus_cli.commands.server.subprocess.run")
    def test_start_detach_success(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli_app, ["server", "start", "--detach"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("argus_cli.commands.server.subprocess.run")
    def test_start_not_found(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        mock_run.side_effect = FileNotFoundError
        result = runner.invoke(cli_app, ["server", "start", "--detach"])
        assert result.exit_code == 1

    @patch("argus_cli.commands.server.subprocess.run")
    def test_start_failed(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
        result = runner.invoke(cli_app, ["server", "start", "--detach"])
        assert result.exit_code == 1


# stop
class TestStop:
    def test_stop_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.shutdown.return_value = {"shutting_down": True}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["server", "stop"])
            assert result.exit_code == 0

    def test_stop_not_acknowledged(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.shutdown.return_value = {"shutting_down": False}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["server", "stop"])
            assert result.exit_code == 1

    def test_stop_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.shutdown.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["server", "stop"])
            assert result.exit_code == 1


# status
class TestStatus:
    def test_status_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.return_value = {
            "service": {
                "name": "argus",
                "version": "1.0",
                "state": "running",
                "uptime_seconds": 3600,
                "started_at": "2025-01-01T00:00:00Z",
            },
            "config": {"file_path": "/etc/argus.yaml", "loaded_at": "now", "backend_count": 2},
            "transport": {"host": "127.0.0.1", "port": 9000},
            "feature_flags": {"optimizer": True},
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["server", "status", "--output", "json"])
            assert result.exit_code == 0

    def test_status_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.side_effect = ArgusClientError(500, "error", "unavailable")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["server", "status"])
            assert result.exit_code == 1


# build
class TestBuild:
    @patch("argus_cli.commands.server.subprocess.run")
    def test_build_success(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli_app, ["server", "build"])
        assert result.exit_code == 0

    @patch("argus_cli.commands.server.subprocess.run")
    def test_build_not_found(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        mock_run.side_effect = FileNotFoundError
        result = runner.invoke(cli_app, ["server", "build"])
        assert result.exit_code == 1

    @patch("argus_cli.commands.server.subprocess.run")
    def test_build_failed(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
        result = runner.invoke(cli_app, ["server", "build"])
        assert result.exit_code == 1


# clean
class TestClean:
    def test_clean_no_flags(self, cli_app: typer.Typer) -> None:
        """Clean without any flags exits with error."""
        result = runner.invoke(cli_app, ["server", "clean"])
        assert result.exit_code == 1

    @patch("argus_cli.commands.server._run_optional")
    def test_clean_images(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["server", "clean", "--images"])
        assert result.exit_code == 0

    @patch("argus_cli.commands.server._run_optional")
    def test_clean_all(self, mock_run: MagicMock, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["server", "clean", "--all"])
        assert result.exit_code == 0
