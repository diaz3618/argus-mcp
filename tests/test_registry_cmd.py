"""Tests for registry CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.registry import app  # noqa: E402
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

    parent.add_typer(app, name="registry")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# ── search ─────────────────────────────────────────────────────────────


class TestSearch:
    def test_search_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.registry_search.return_value = {
            "registry": "glama",
            "servers": [
                {"name": "fetch", "description": "Web fetcher", "transport": "stdio"},
            ],
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["registry", "search", "fetch", "--output", "json"])
            assert result.exit_code == 0

    def test_search_no_results(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.registry_search.return_value = {"servers": []}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["registry", "search", "nonexistent"])
            assert result.exit_code == 0

    def test_search_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.registry_search.side_effect = ArgusClientError(500, "error", "search failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["registry", "search", "test"])
            assert result.exit_code == 1


# ── inspect ────────────────────────────────────────────────────────────


class TestInspect:
    def test_inspect_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.backends.return_value = {
            "backends": [
                {
                    "name": "fetch",
                    "type": "stdio",
                    "group": "default",
                    "state": "connected",
                    "capabilities": {"tools": 2, "resources": 1, "prompts": 0},
                }
            ]
        }
        mock_client.capabilities.return_value = {
            "tools": [{"name": "web_fetch", "description": "Fetch a URL"}],
            "resources": [{"uri": "web://page", "mime_type": "text/html"}],
            "prompts": [],
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["registry", "inspect", "fetch", "--output", "json"])
            assert result.exit_code == 0

    def test_inspect_not_found(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.backends.return_value = {"backends": []}
        mock_client.capabilities.return_value = {"tools": [], "resources": [], "prompts": []}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["registry", "inspect", "missing"])
            assert result.exit_code == 1

    def test_inspect_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.backends.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["registry", "inspect", "test"])
            assert result.exit_code == 1


# ── install ────────────────────────────────────────────────────────────


class TestInstall:
    def test_install_no_config(self, cli_app: typer.Typer) -> None:
        """Install without --config just prints the entry."""
        result = runner.invoke(
            cli_app,
            ["registry", "install", "new-be", "--type", "stdio", "--command", "echo hi"],
        )
        assert result.exit_code == 0

    def test_install_with_config(
        self, cli_app: typer.Typer, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Install with --config writes to the config file."""
        config_file = tmp_path / "config.yaml"  # type: ignore[operator]
        config_file.write_text("backends: {}\n")

        mock_client = MagicMock()
        mock_client.reload.return_value = {"backends_added": 1}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(
                cli_app,
                [
                    "registry",
                    "install",
                    "new-be",
                    "--type",
                    "stdio",
                    "--command",
                    "echo hi",
                    "--config",
                    str(config_file),
                ],
            )
            assert result.exit_code == 0

    def test_install_duplicate(
        self, cli_app: typer.Typer, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Install fails if backend name already exists in config."""
        config_file = tmp_path / "config.yaml"  # type: ignore[operator]
        config_file.write_text("backends:\n  new-be:\n    type: stdio\n")

        result = runner.invoke(
            cli_app,
            [
                "registry",
                "install",
                "new-be",
                "--type",
                "stdio",
                "--config",
                str(config_file),
            ],
        )
        assert result.exit_code == 1
