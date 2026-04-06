"""Tests for auth CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.auth import app  # noqa: E402
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

    parent.add_typer(app, name="auth")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# ── status ─────────────────────────────────────────────────────────────


class TestAuthStatus:
    def test_status_connected(self, cli_app: typer.Typer) -> None:
        """status always exits 0 — catches ArgusClientError internally and sets
        server_status to 'disconnected'. When server is reachable, shows health info."""
        mock_client = MagicMock()
        mock_client.health.return_value = {"status": "healthy", "version": "1.0.0"}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["auth", "status", "--output", "json"])
            assert result.exit_code == 0

    def test_status_disconnected(self, cli_app: typer.Typer) -> None:
        """When server is unreachable, status still exits 0 with 'disconnected'."""
        mock_client = MagicMock()
        mock_client.health.side_effect = ArgusClientError(401, "unauthorized", "bad token")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["auth", "status", "--output", "json"])
            # status command NEVER exits 1 — it catches errors and shows disconnected
            assert result.exit_code == 0


# ── configure ──────────────────────────────────────────────────────────


class TestAuthConfigure:
    def test_configure_with_token(self, cli_app: typer.Typer) -> None:
        """configure patches _load_yaml_config/_save_yaml_config from argus_cli.config."""
        with (
            patch("argus_cli.config._load_yaml_config", return_value={}),
            patch("argus_cli.config._save_yaml_config") as mock_save,
            patch("argus_cli.config.CONFIG_FILE"),
        ):
            result = runner.invoke(
                cli_app,
                ["auth", "configure", "--mode", "bearer", "--token", "abc123"],
            )
            assert result.exit_code == 0
            mock_save.assert_called_once()

    def test_configure_no_args(self, cli_app: typer.Typer) -> None:
        """configure with neither --mode nor --token exits 1."""
        result = runner.invoke(cli_app, ["auth", "configure"])
        assert result.exit_code == 1

    def test_configure_invalid_mode(self, cli_app: typer.Typer) -> None:
        """configure with invalid auth mode exits 1."""
        result = runner.invoke(cli_app, ["auth", "configure", "--mode", "invalid"])
        assert result.exit_code == 1


# ── test ───────────────────────────────────────────────────────────────


class TestAuthTest:
    def test_test_connection_ok(self, cli_app: typer.Typer) -> None:
        """test command calls client.status() (not client.health())."""
        mock_client = MagicMock()
        mock_client.status.return_value = {"version": "1.0.0"}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["auth", "test"])
            assert result.exit_code == 0

    def test_test_connection_fail(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.status.side_effect = ArgusClientError(500, "error", "unreachable")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["auth", "test"])
            assert result.exit_code == 1
