"""Tests for audit CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.audit import app  # noqa: E402
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
        },
        {
            "timestamp": "2025-01-01T00:01:00Z",
            "stage": "backend",
            "severity": "warning",
            "message": "backend slow",
        },
    ]
}


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="audit")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# ── list ───────────────────────────────────────────────────────────────


class TestAuditList:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.events.return_value = _SAMPLE_EVENTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["audit", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_with_limit(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.events.return_value = _SAMPLE_EVENTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["audit", "list", "--limit", "5", "--output", "json"])
            assert result.exit_code == 0

    def test_list_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.events.side_effect = ArgusClientError(500, "error", "failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["audit", "list"])
            assert result.exit_code == 1


# ── export ─────────────────────────────────────────────────────────────


class TestAuditExport:
    def test_export_json(self, cli_app: typer.Typer, tmp_path) -> None:
        mock_client = MagicMock()
        mock_client.events.return_value = _SAMPLE_EVENTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        out_file = tmp_path / "events.json"
        with patch(_PATCH, return_value=mock_client):
            # export uses --format/-f for format and --output/-o for file path
            result = runner.invoke(
                cli_app, ["audit", "export", "--format", "json", "--output", str(out_file)]
            )
            assert result.exit_code == 0

    def test_export_csv(self, cli_app: typer.Typer, tmp_path) -> None:
        mock_client = MagicMock()
        mock_client.events.return_value = _SAMPLE_EVENTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        out_file = tmp_path / "events.csv"
        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(
                cli_app, ["audit", "export", "--format", "csv", "--output", str(out_file)]
            )
            assert result.exit_code == 0

    def test_export_stdout(self, cli_app: typer.Typer) -> None:
        """Export to stdout when no --output is given."""
        mock_client = MagicMock()
        mock_client.events.return_value = _SAMPLE_EVENTS
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["audit", "export", "--format", "json"])
            assert result.exit_code == 0

    def test_export_error(self, cli_app: typer.Typer) -> None:
        mock_client = MagicMock()
        mock_client.events.side_effect = ArgusClientError(500, "error", "fail")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH, return_value=mock_client):
            result = runner.invoke(cli_app, ["audit", "export"])
            assert result.exit_code == 1
