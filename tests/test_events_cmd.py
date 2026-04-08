"""Tests for events CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.events import app  # noqa: E402
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

_SAMPLE_EVENTS = {
    "events": [
        {
            "timestamp": "2025-01-01T00:00:00Z",
            "stage": "startup",
            "severity": "info",
            "message": "server started",
        }
    ]
}


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="events")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# list
class TestListEvents:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.events.return_value = _SAMPLE_EVENTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["events", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_with_filters(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.events.return_value = _SAMPLE_EVENTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(
                cli_app,
                ["events", "list", "--limit", "10", "--severity", "warning", "--output", "json"],
            )
            assert result.exit_code == 0

    def test_list_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.events.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["events", "list"])
            assert result.exit_code == 1


# stream
class TestStreamEvents:
    def test_stream_keyboard_interrupt(self, cli_app: typer.Typer) -> None:
        """Stream command uses asyncio.run internally; patch it to simulate interrupt."""
        # The stream function imports asyncio inside its body, so we patch
        # the built-in asyncio.run at the top-level asyncio module
        with patch("asyncio.run", side_effect=KeyboardInterrupt):
            result = runner.invoke(cli_app, ["events", "stream"])
            # KeyboardInterrupt is caught by the stream command, exits 0
            assert result.exit_code == 0

    def test_stream_invokes(self, cli_app: typer.Typer) -> None:
        """Verify the stream command calls asyncio.run."""
        with patch("asyncio.run", return_value=None) as mock_run:
            result = runner.invoke(cli_app, ["events", "stream"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
