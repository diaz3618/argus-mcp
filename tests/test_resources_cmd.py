"""Tests for resources CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.resources import app  # noqa: E402
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

    parent.add_typer(app, name="resources")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# list
class TestListResources:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.capabilities.return_value = {
            "resources": [{"name": "config://main", "uri": "config://main", "backend": "test"}]
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["resources", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.capabilities.side_effect = ArgusClientError(500, "error", "fail")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["resources", "list"])
            assert result.exit_code == 1


# read
class TestReadResource:
    def test_read_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.read_resource.return_value = {
            "contents": [{"text": "resource content here", "uri": "config://main"}]
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["resources", "read", "config://main"])
            assert result.exit_code == 0

    def test_read_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.read_resource.side_effect = ArgusClientError(
            404, "not_found", "resource not found"
        )
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["resources", "read", "config://missing"])
            assert result.exit_code == 1
