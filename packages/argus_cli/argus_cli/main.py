"""Typer app root — CLI entry point, global options, command group registration."""

from __future__ import annotations

from typing import Annotated

import typer

from argus_cli import __version__
from argus_cli.config import CliConfig, get_config, is_repl_mode, set_config

# ── Typer app ──────────────────────────────────────────────────────────

app = typer.Typer(
    name="argus",
    help="Interactive CLI for Argus MCP — manage backends, tools, events, and more.",
    rich_markup_mode="rich",
    no_args_is_help=False,
    add_completion=True,
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
    invoke_without_command=True,
)


# ── Global options callback ────────────────────────────────────────────


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"argus-cli {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            "-s",
            help="Argus server base URL, e.g. http://127.0.0.1:9000 (no /mcp suffix).",
            envvar="ARGUS_SERVER_URL",
            rich_help_panel="Connection",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            help="Management API token.",
            envvar="ARGUS_MGMT_TOKEN",
            rich_help_panel="Connection",
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help="Output format: rich, json, table, text.",
            rich_help_panel="Display",
        ),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option(
            "--theme",
            help="Color theme name (see: argus config themes).",
            rich_help_panel="Display",
        ),
    ] = None,
    no_color: Annotated[
        bool,
        typer.Option(
            "--no-color",
            help="Disable colored output.",
            rich_help_panel="Display",
        ),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show version.",
        ),
    ] = None,
) -> None:
    """Argus MCP interactive CLI — manage your MCP server from the terminal."""
    # When dispatched from the REPL, skip re-resolution — config is already set.
    if is_repl_mode():
        ctx.obj = get_config()
        return

    _config = CliConfig.resolve(
        server=server,
        token=token,
        output=output,
        no_color=no_color,
        theme=theme,
    )
    set_config(_config)
    ctx.obj = _config

    # Apply configured theme
    from argus_cli.theme import set_active_theme

    set_active_theme(_config.theme)

    # No subcommand → launch REPL
    if ctx.invoked_subcommand is None:
        from argus_cli.repl import start_repl

        start_repl(_config)


# ── Command group registration ─────────────────────────────────────────
# Import and register sub-apps. Each module creates its own typer.Typer()
# instance that gets added as a command group.


def _register_commands() -> None:
    """Import and register all command group sub-apps."""
    from argus_cli.commands.audit import app as audit_app
    from argus_cli.commands.auth import app as auth_app
    from argus_cli.commands.backends import app as backends_app
    from argus_cli.commands.batch import app as batch_app
    from argus_cli.commands.config_cmd import app as config_app
    from argus_cli.commands.containers import app as containers_app
    from argus_cli.commands.events import app as events_app
    from argus_cli.commands.health import app as health_app
    from argus_cli.commands.operations import app as operations_app
    from argus_cli.commands.pods import app as pods_app
    from argus_cli.commands.prompts import app as prompts_app
    from argus_cli.commands.registry import app as registry_app
    from argus_cli.commands.resources import app as resources_app
    from argus_cli.commands.secrets import app as secrets_app
    from argus_cli.commands.server import app as server_app
    from argus_cli.commands.skills import app as skills_app
    from argus_cli.commands.tools import app as tools_app
    from argus_cli.commands.workflows import app as workflows_app

    app.add_typer(
        server_app, name="server", help="Server lifecycle management.", rich_help_panel="Server"
    )
    app.add_typer(
        backends_app,
        name="backends",
        help="Backend management and inspection.",
        rich_help_panel="Server",
    )
    app.add_typer(
        tools_app, name="tools", help="MCP tools — list, inspect, call.", rich_help_panel="MCP"
    )
    app.add_typer(
        resources_app, name="resources", help="MCP resources — list, read.", rich_help_panel="MCP"
    )
    app.add_typer(
        prompts_app, name="prompts", help="MCP prompts — list, get.", rich_help_panel="MCP"
    )
    app.add_typer(
        registry_app,
        name="registry",
        help="Server registry — search, install.",
        rich_help_panel="MCP",
    )
    app.add_typer(
        config_app, name="config", help="Configuration management.", rich_help_panel="Configuration"
    )
    app.add_typer(
        secrets_app, name="secrets", help="Secrets management.", rich_help_panel="Configuration"
    )
    app.add_typer(
        auth_app, name="auth", help="Authentication configuration.", rich_help_panel="Configuration"
    )
    app.add_typer(
        health_app, name="health", help="Health status and sessions.", rich_help_panel="Monitoring"
    )
    app.add_typer(audit_app, name="audit", help="Audit log queries.", rich_help_panel="Monitoring")
    app.add_typer(
        events_app, name="events", help="Events — list, stream (SSE).", rich_help_panel="Monitoring"
    )
    app.add_typer(skills_app, name="skills", help="Skills management.", rich_help_panel="MCP")
    app.add_typer(
        workflows_app, name="workflows", help="Workflow execution.", rich_help_panel="Operations"
    )
    app.add_typer(
        operations_app,
        name="operations",
        help="Optimizer and telemetry.",
        rich_help_panel="Operations",
    )
    app.add_typer(batch_app, name="batch", help="Bulk operations.", rich_help_panel="Operations")
    app.add_typer(
        containers_app,
        name="containers",
        help="Container management — list, logs, stats, lifecycle.",
        rich_help_panel="Infrastructure",
    )
    app.add_typer(
        pods_app,
        name="pods",
        help="Kubernetes pod management — list, logs, events, lifecycle.",
        rich_help_panel="Infrastructure",
    )


_register_commands()


# ── Shell / REPL entry ─────────────────────────────────────────────────


@app.command()
def shell() -> None:
    """Enter the interactive REPL shell."""
    from argus_cli.repl import start_repl

    config = get_config()
    start_repl(config)


@app.command()
def tui(
    server: Annotated[
        str | None,
        typer.Option("--server", "-s", help="Argus server URL."),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", "-t", help="Management API token."),
    ] = None,
) -> None:
    """Launch the Textual TUI dashboard."""
    try:
        from argus_cli.tui.app import ArgusApp
    except ImportError:
        typer.echo(
            "Textual TUI requires the 'tui' extra: pip install argus-cli[tui]",
            err=True,
        )
        raise typer.Exit(1) from None

    config = get_config()
    url = server or config.server_url
    tok = token or config.token
    app_instance = ArgusApp(server_url=url, token=tok)
    app_instance.run()
