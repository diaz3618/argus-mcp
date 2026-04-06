"""Tests for secrets CLI commands (filesystem-only, no ArgusClient)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.commands.secrets import app  # noqa: E402
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

    parent.add_typer(app, name="secrets")
    return parent


@pytest.fixture()
def cli_app() -> typer.Typer:
    return _wrap_app()


# ── list ───────────────────────────────────────────────────────────────


class TestListSecrets:
    def test_list_empty(self, cli_app: typer.Typer, tmp_path) -> None:
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        with patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir):
            result = runner.invoke(cli_app, ["secrets", "list"])
            assert result.exit_code == 0

    def test_list_with_secrets(self, cli_app: typer.Typer, tmp_path) -> None:
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "API_KEY").write_text("secret-value")
        (secrets_dir / "DB_PASS").write_text("db-secret")
        with patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir):
            result = runner.invoke(cli_app, ["secrets", "list"])
            assert result.exit_code == 0


# ── set ────────────────────────────────────────────────────────────────


class TestSetSecret:
    def test_set_success(self, cli_app: typer.Typer, tmp_path) -> None:
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        with patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir):
            result = runner.invoke(cli_app, ["secrets", "set", "MY_KEY", "my-value"])
            assert result.exit_code == 0
            assert (secrets_dir / "MY_KEY").read_text() == "my-value"

    def test_set_prompts_when_no_value(self, cli_app: typer.Typer, tmp_path) -> None:
        """When value is omitted, set_secret prompts via getpass."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        with (
            patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir),
            patch("getpass.getpass", return_value="prompted-value"),
        ):
            result = runner.invoke(cli_app, ["secrets", "set", "PROMPT_KEY"])
            assert result.exit_code == 0
            assert (secrets_dir / "PROMPT_KEY").read_text() == "prompted-value"


# ── get ────────────────────────────────────────────────────────────────


class TestGetSecret:
    def test_get_success(self, cli_app: typer.Typer, tmp_path) -> None:
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "API_KEY").write_text("secret-123")
        with patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir):
            result = runner.invoke(cli_app, ["secrets", "get", "API_KEY"])
            assert result.exit_code == 0

    def test_get_not_found(self, cli_app: typer.Typer, tmp_path) -> None:
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        with patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir):
            result = runner.invoke(cli_app, ["secrets", "get", "MISSING"])
            assert result.exit_code == 1


# ── delete ─────────────────────────────────────────────────────────────


class TestDeleteSecret:
    def test_delete_success(self, cli_app: typer.Typer, tmp_path) -> None:
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "OLD_KEY").write_text("old-value")
        with patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir):
            result = runner.invoke(cli_app, ["secrets", "delete", "OLD_KEY"])
            assert result.exit_code == 0
            assert not (secrets_dir / "OLD_KEY").exists()

    def test_delete_not_found(self, cli_app: typer.Typer, tmp_path) -> None:
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        with patch("argus_cli.commands.secrets._secrets_dir", return_value=secrets_dir):
            result = runner.invoke(cli_app, ["secrets", "delete", "MISSING"])
            assert result.exit_code == 1
