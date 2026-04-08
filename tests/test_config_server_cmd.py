"""Tests for config_server CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.config_server import app  # noqa: E402
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

    parent.add_typer(app, name="config-server")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


def _mc(**overrides) -> MagicMock:
    mc = MagicMock()
    mc.__enter__ = MagicMock(return_value=mc)
    mc.__exit__ = MagicMock(return_value=False)
    for k, v in overrides.items():
        setattr(mc, k, v)
    return mc


# show
class TestConfigShow:
    def test_show_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.status.return_value = {"config": {"version": "1", "mcpServers": {}}}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["config-server", "show", "--output", "json"])
            assert result.exit_code == 0

    def test_show_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.status.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["config-server", "show"])
            assert result.exit_code == 1


# validate
class TestConfigValidate:
    def test_validate_valid(self, cli_app: typer.Typer, tmp_path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text('version: "1"\nbackends:\n  test:\n    type: stdio\n')
        with patch(
            "argus_cli.commands.config_server._resolve_config_path",
            return_value=cfg_file,
        ):
            result = runner.invoke(cli_app, ["config-server", "validate"])
            assert result.exit_code == 0


# reload
class TestConfigReload:
    def test_reload_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.reload.return_value = {"reloaded": True}
        mock_console = MagicMock()
        mock_console.status.return_value.__enter__ = MagicMock()
        mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(_PATCH, return_value=mc),
            patch("argus_cli.output.get_console", return_value=mock_console),
        ):
            result = runner.invoke(cli_app, ["config-server", "reload"])
            assert result.exit_code == 0

    def test_reload_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.reload.side_effect = ArgusClientError(500, "error", "fail")
        mock_console = MagicMock()
        mock_console.status.return_value.__enter__ = MagicMock()
        mock_console.status.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch(_PATCH, return_value=mc),
            patch("argus_cli.output.get_console", return_value=mock_console),
        ):
            result = runner.invoke(cli_app, ["config-server", "reload"])
            assert result.exit_code == 1


# export
class TestConfigExport:
    def test_export_json_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.status.return_value = {"config": {"version": "1", "mcpServers": {}}}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["config-server", "export", "--format", "json"])
            assert result.exit_code == 0

    def test_export_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.status.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["config-server", "export"])
            assert result.exit_code == 1


# diff
class TestConfigDiff:
    def test_diff_success(self, cli_app: typer.Typer, tmp_path) -> None:
        mc = _mc()
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text('version: "1"\nmcpServers:\n  test:\n    type: stdio\n')
        mc.status.return_value = {
            "config": {
                "file_path": str(cfg_file),
                "version": "1",
                "mcpServers": {},
            }
        }
        mock_console = MagicMock()
        with (
            patch(_PATCH, return_value=mc),
            patch("argus_cli.output.get_console", return_value=mock_console),
            # Allow file_path to pass the allowed-dirs check
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            result = runner.invoke(cli_app, ["config-server", "diff"])
            assert result.exit_code == 0

    def test_diff_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.status.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["config-server", "diff"])
            assert result.exit_code == 1
