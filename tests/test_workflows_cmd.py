"""Tests for workflows CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.workflows import BUILTIN_WORKFLOWS, app  # noqa: E402
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

    parent.add_typer(app, name="workflows")
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


# ── list ───────────────────────────────────────────────────────────────


class TestListWorkflows:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["workflows", "list", "--output", "json"])
        assert result.exit_code == 0

    def test_list_shows_builtin(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["workflows", "list"])
        assert result.exit_code == 0
        # Verify built-in workflow names appear
        for name in BUILTIN_WORKFLOWS:
            assert name in result.output


# ── run ────────────────────────────────────────────────────────────────


class TestRunWorkflow:
    def test_run_dry_run(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["workflows", "run", "health-check", "--dry-run"])
        assert result.exit_code == 0
        assert "Step" in result.output

    def test_run_not_found(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["workflows", "run", "nonexistent"])
        assert result.exit_code == 1

    def test_run_executes_steps(self, cli_app: typer.Typer) -> None:
        mock_console = MagicMock()
        with (
            patch("argus_cli.main.app") as mock_root,
            patch("argus_cli.output.get_console", return_value=mock_console),
        ):
            mock_root.return_value = None
            result = runner.invoke(cli_app, ["workflows", "run", "health-check"])
            assert result.exit_code == 0
            assert mock_root.call_count == len(BUILTIN_WORKFLOWS["health-check"]["steps"])

    def test_run_step_failure(self, cli_app: typer.Typer) -> None:
        mock_console = MagicMock()
        with (
            patch("argus_cli.main.app") as mock_root,
            patch("argus_cli.output.get_console", return_value=mock_console),
        ):
            mock_root.side_effect = SystemExit(1)
            result = runner.invoke(cli_app, ["workflows", "run", "health-check"])
            assert result.exit_code == 1


# ── history ────────────────────────────────────────────────────────────


class TestWorkflowHistory:
    def test_history_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.events.return_value = {
            "events": [
                {
                    "timestamp": "2025-01-01T00:00:00Z",
                    "stage": "workflow",
                    "severity": "info",
                    "message": "workflow health-check started",
                },
            ]
        }
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["workflows", "history", "--output", "json"])
            assert result.exit_code == 0

    def test_history_empty(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.events.return_value = {
            "events": [
                {
                    "timestamp": "2025-01-01T00:00:00Z",
                    "stage": "startup",
                    "severity": "info",
                    "message": "server started",
                },
            ]
        }
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["workflows", "history"])
            assert result.exit_code == 0

    def test_history_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.events.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["workflows", "history"])
            assert result.exit_code == 1
