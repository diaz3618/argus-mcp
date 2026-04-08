"""Tests for batch CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.batch import app  # noqa: E402
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
        {"name": "be-1", "type": "stdio", "state": "connected"},
        {"name": "be-2", "type": "sse", "state": "connected"},
    ]
}


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="batch")
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


# reconnect-all
# reconnect_all uses --yes/-y flag, calls client.backends() then
# client.reconnect(name) per backend with Progress context manager


class TestBatchReconnectAll:
    def test_reconnect_all_confirmed(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.backends.return_value = _SAMPLE_BACKENDS
        mc.reconnect.return_value = {"reconnected": True}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["batch", "reconnect-all", "--yes"])
            assert result.exit_code == 0

    def test_reconnect_all_aborted(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["batch", "reconnect-all"], input="n\n")
        assert result.exit_code != 0

    def test_reconnect_all_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.backends.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["batch", "reconnect-all", "--yes"])
            assert result.exit_code == 1


# restart-all
# restart_all uses --yes/-y flag, calls client.reload() (not client.restart_all)


class TestBatchRestartAll:
    def test_restart_all_confirmed(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.reload.return_value = {
            "reloaded": True,
            "backends_added": 0,
            "backends_removed": 0,
            "backends_changed": 0,
        }
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["batch", "restart-all", "--yes"])
            assert result.exit_code == 0

    def test_restart_all_aborted(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["batch", "restart-all"], input="n\n")
        assert result.exit_code != 0

    def test_restart_all_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.reload.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["batch", "restart-all", "--yes"])
            assert result.exit_code == 1
