"""Tests for tools CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.tools import app  # noqa: E402
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

    parent.add_typer(app, name="tools")
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


class TestListTools:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.capabilities.return_value = {
            "tools": [{"name": "echo", "description": "Echo input", "backend": "test-be"}]
        }
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.capabilities.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "list"])
            assert result.exit_code == 1


# ── inspect ────────────────────────────────────────────────────────────
# inspect calls client.capabilities(type_filter="tools", search=name)
# and finds matching tool by name in the returned list


class TestInspectTool:
    def test_inspect_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.capabilities.return_value = {
            "tools": [
                {
                    "name": "echo",
                    "original_name": "echo",
                    "backend": "test-be",
                    "description": "Echo input",
                    "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                    "renamed": False,
                    "filtered": False,
                }
            ]
        }
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "inspect", "echo", "--output", "json"])
            assert result.exit_code == 0

    def test_inspect_not_found(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.capabilities.return_value = {"tools": []}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "inspect", "missing"])
            assert result.exit_code == 1

    def test_inspect_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.capabilities.side_effect = ArgusClientError(404, "not_found", "tool not found")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "inspect", "missing"])
            assert result.exit_code == 1


# ── call ───────────────────────────────────────────────────────────────


class TestCallTool:
    def test_call_with_args(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.call_tool.return_value = {"content": [{"type": "text", "text": "hello"}]}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "call", "echo", "--arg", "text=hello"])
            assert result.exit_code == 0

    def test_call_with_json(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.call_tool.return_value = {"content": [{"type": "text", "text": "ok"}]}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "call", "echo", "--json", '{"text": "hi"}'])
            assert result.exit_code == 0

    def test_call_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.call_tool.side_effect = ArgusClientError(500, "error", "tool failed")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["tools", "call", "echo", "--arg", "text=hi"])
            assert result.exit_code == 1


# ── rename ─────────────────────────────────────────────────────────────
# rename is LOCAL-ONLY (no client call). It takes --to for the new name
# and just prints instructions to modify config.


class TestRenameTool:
    def test_rename_prints_instructions(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["tools", "rename", "old-tool", "--to", "new-tool"])
        assert result.exit_code == 0
        assert "rename" in result.output.lower() or "config" in result.output.lower()

    def test_rename_with_description(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(
            cli_app, ["tools", "rename", "old-tool", "--to", "new-tool", "--description", "Updated"]
        )
        assert result.exit_code == 0


# ── filter ─────────────────────────────────────────────────────────────
# filter is LOCAL-ONLY (no client call). Takes --allow/--deny patterns.
# With no args, exits 1.


class TestFilterTool:
    def test_filter_with_allow(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["tools", "filter", "--allow", "echo*"])
        assert result.exit_code == 0

    def test_filter_with_deny(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["tools", "filter", "--deny", "dangerous*"])
        assert result.exit_code == 0

    def test_filter_no_args_exits_1(self, cli_app: typer.Typer) -> None:
        result = runner.invoke(cli_app, ["tools", "filter"])
        assert result.exit_code == 1
