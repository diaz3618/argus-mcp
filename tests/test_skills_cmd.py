"""Tests for skills CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

import typer  # noqa: E402
from argus_cli.client import ArgusClientError  # noqa: E402
from argus_cli.commands.skills import app  # noqa: E402
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

_SAMPLE_SKILLS = [
    {
        "name": "code-review",
        "description": "Review code changes",
        "status": "enabled",
        "version": "1.0",
    },
    {"name": "summarize", "description": "Summarize text", "status": "disabled", "version": "0.9"},
]


def _wrap_app() -> typer.Typer:
    parent = typer.Typer()

    @parent.callback(invoke_without_command=True)
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = make_cli_config()

    parent.add_typer(app, name="skills")
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


# list
# list uses _fetch_skills(cfg) which calls client.skills_list()


class TestListSkills:
    def test_list_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_list.return_value = {"skills": _SAMPLE_SKILLS}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "list", "--output", "json"])
            assert result.exit_code == 0

    def test_list_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_list.side_effect = ArgusClientError(500, "error", "fail")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "list"])
            assert result.exit_code == 1


# inspect
# inspect uses _fetch_skills(cfg) to find skill by name in list


class TestInspectSkill:
    def test_inspect_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_list.return_value = {"skills": _SAMPLE_SKILLS}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(
                cli_app, ["skills", "inspect", "code-review", "--output", "json"]
            )
            assert result.exit_code == 0

    def test_inspect_not_found(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_list.return_value = {"skills": _SAMPLE_SKILLS}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "inspect", "missing"])
            assert result.exit_code == 1

    def test_inspect_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_list.side_effect = ArgusClientError(404, "not_found", "not found")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "inspect", "missing"])
            assert result.exit_code == 1


# enable
# enable calls client.skills_enable(name), checks data.get("ok")


class TestEnableSkill:
    def test_enable_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_enable.return_value = {"ok": True}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "enable", "summarize"])
            assert result.exit_code == 0

    def test_enable_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_enable.side_effect = ArgusClientError(404, "not_found", "not found")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "enable", "missing"])
            assert result.exit_code == 1


# disable
# disable calls client.skills_disable(name), checks data.get("ok")


class TestDisableSkill:
    def test_disable_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_disable.return_value = {"ok": True}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "disable", "code-review"])
            assert result.exit_code == 0

    def test_disable_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_disable.side_effect = ArgusClientError(404, "not_found", "not found")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "disable", "missing"])
            assert result.exit_code == 1


# apply
# apply takes TWO positional arguments: name and target
# apply with --dry-run calls _fetch_skills() to find the skill
# apply without --dry-run calls client.skills_enable(name)


class TestApplySkill:
    def test_apply_success(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_enable.return_value = {"ok": True}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "apply", "code-review", "backend-1"])
            assert result.exit_code == 0

    def test_apply_dry_run(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_list.return_value = {"skills": _SAMPLE_SKILLS}
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(
                cli_app,
                ["skills", "apply", "code-review", "backend-1", "--dry-run"],
            )
            assert result.exit_code == 0

    def test_apply_error(self, cli_app: typer.Typer) -> None:
        mc = _mc()
        mc.skills_enable.side_effect = ArgusClientError(500, "error", "apply failed")
        with patch(_PATCH, return_value=mc):
            result = runner.invoke(cli_app, ["skills", "apply", "code-review", "backend-1"])
            assert result.exit_code == 1
