"""Tests for operations CLI commands (optimizer, telemetry subgroups)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.operations import app  # noqa: E402
from typer.testing import CliRunner  # noqa: E402


def make_cli_config():
    """Create a mock CLI config for ArgusClient-based commands."""
    cfg = MagicMock()
    cfg.output_format = "json"
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

    parent.add_typer(app, name="operations")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# optimizer status
class TestOptimizerStatus:
    def test_optimizer_status_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.return_value = {
            "feature_flags": {
                "optimizer": {
                    "enabled": True,
                    "keep_list": ["tool-a"],
                    "strategy": "aggressive",
                }
            }
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["operations", "optimizer", "status", "--output", "json"]
            )
            assert result.exit_code == 0

    def test_optimizer_status_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["operations", "optimizer", "status"])
            assert result.exit_code == 1


# optimizer enable/disable
class TestOptimizerToggle:
    def test_optimizer_enable_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.reload.return_value = {"errors": []}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_console = MagicMock()
        mock_console.status.return_value.__enter__ = MagicMock()
        mock_console.status.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch(_PATCH, return_value=mock_client),
            patch("argus_cli.output.get_console", return_value=mock_console),
            patch("argus_cli.output.print_warning"),
        ):
            result = runner.invoke(cli_app, ["operations", "optimizer", "enable"])
            assert result.exit_code == 0

    def test_optimizer_disable_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.reload.return_value = {"errors": []}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_console = MagicMock()
        mock_console.status.return_value.__enter__ = MagicMock()
        mock_console.status.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch(_PATCH, return_value=mock_client),
            patch("argus_cli.output.get_console", return_value=mock_console),
            patch("argus_cli.output.print_warning"),
        ):
            result = runner.invoke(cli_app, ["operations", "optimizer", "disable"])
            assert result.exit_code == 0

    def test_optimizer_enable_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.reload.side_effect = ArgusClientError(500, "error", "reload failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_console = MagicMock()
        mock_console.status.return_value.__enter__ = MagicMock()
        mock_console.status.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch(_PATCH, return_value=mock_client),
            patch("argus_cli.output.get_console", return_value=mock_console),
            patch("argus_cli.output.print_warning"),
        ):
            result = runner.invoke(cli_app, ["operations", "optimizer", "enable"])
            assert result.exit_code == 1


# telemetry status
class TestTelemetryStatus:
    def test_telemetry_status_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.return_value = {
            "feature_flags": {
                "telemetry": {
                    "enabled": True,
                    "endpoint": "http://otel:4317",
                    "service_name": "argus-mcp",
                    "protocol": "otlp",
                }
            }
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["operations", "telemetry", "status", "--output", "json"]
            )
            assert result.exit_code == 0

    def test_telemetry_status_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["operations", "telemetry", "status"])
            assert result.exit_code == 1


# telemetry configure
class TestTelemetryConfigure:
    def test_configure_with_endpoint(self, cli_app: typer.Typer) -> None:
        with patch("argus_cli.output.print_warning"):
            result = runner.invoke(
                cli_app,
                ["operations", "telemetry", "configure", "--endpoint", "http://otel:4317"],
            )
            assert result.exit_code == 0

    def test_configure_no_changes(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["operations", "telemetry", "configure"])
        assert result.exit_code == 0
