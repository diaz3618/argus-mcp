"""Tests for config_cmd CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.commands.config_cmd import app  # noqa: E402
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


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="config")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# ── init ───────────────────────────────────────────────────────────────


class TestConfigInit:
    def test_init_creates_file(self, cli_app: typer.Typer, tmp_path) -> None:
        config_file = tmp_path / "config.yaml"
        config_dir = tmp_path
        with (
            patch("argus_cli.config.CONFIG_FILE", config_file),
            patch("argus_cli.config.CONFIG_DIR", config_dir),
        ):
            result = runner.invoke(cli_app, ["config", "init"])
            assert result.exit_code == 0
            assert config_file.exists()

    def test_init_existing_no_force(self, cli_app: typer.Typer, tmp_path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("version: '1'\n")
        config_dir = tmp_path
        with (
            patch("argus_cli.config.CONFIG_FILE", config_file),
            patch("argus_cli.config.CONFIG_DIR", config_dir),
        ):
            result = runner.invoke(cli_app, ["config", "init"])
            # Should fail because file already exists without --force
            assert result.exit_code == 1


# ── local ──────────────────────────────────────────────────────────────


class TestConfigLocal:
    def test_local_shows_config(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["config", "local", "--output", "json"])
        assert result.exit_code == 0


# ── themes ─────────────────────────────────────────────────────────────


class TestConfigThemes:
    def test_themes_lists_palettes(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["config", "themes", "--output", "json"])
        assert result.exit_code == 0
