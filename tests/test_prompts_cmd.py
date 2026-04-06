"""Tests for prompts CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.prompts import app  # noqa: E402
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

_SAMPLE_PROMPTS = {
    "prompts": [
        {
            "name": "code-review",
            "description": "Review code changes",
            "backend": "test",
            "arguments": [{"name": "language", "required": False, "description": "Language"}],
        }
    ]
}


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="prompts")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# ── list ───────────────────────────────────────────────────────────────


class TestListPrompts:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.capabilities.return_value = _SAMPLE_PROMPTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["prompts", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_empty(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.capabilities.return_value = {"prompts": []}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["prompts", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.capabilities.side_effect = ArgusClientError(500, "error", "fail")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["prompts", "list"])
            assert result.exit_code == 1


# ── get ────────────────────────────────────────────────────────────────


class TestGetPrompt:
    def test_get_success(self, cli_app: typer.Typer) -> None:
        """get command calls capabilities(type_filter='prompts', search=name) and
        finds the matching prompt by name in the returned list."""
        mock_client = MagicMock()
        mock_client.capabilities.return_value = _SAMPLE_PROMPTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["prompts", "get", "code-review", "--output", "json"])
            assert result.exit_code == 0

    def test_get_with_args(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.capabilities.return_value = _SAMPLE_PROMPTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(
                cli_app,
                ["prompts", "get", "code-review", "--arg", "language=python", "--output", "json"],
            )
            assert result.exit_code == 0

    def test_get_not_found(self, cli_app: typer.Typer) -> None:
        """When capabilities returns prompts but none match the name, exit 1."""
        mock_client = MagicMock()
        mock_client.capabilities.return_value = {"prompts": []}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["prompts", "get", "nonexistent"])
            assert result.exit_code == 1

    def test_get_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.capabilities.side_effect = ArgusClientError(
            404, "not_found", "prompt not found"
        )
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["prompts", "get", "nonexistent"])
            assert result.exit_code == 1
