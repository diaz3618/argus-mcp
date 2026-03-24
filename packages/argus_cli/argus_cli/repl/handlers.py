"""REPL-exclusive command handlers (not dispatched to Typer)."""

from __future__ import annotations

__all__ = [
    "handle_alias",
    "handle_connect",
    "handle_history",
    "handle_set",
    "handle_unalias",
    "handle_use",
    "handle_watch",
    "show_banner",
    "show_help",
]

import time as _time
from pathlib import Path

from rich.console import Console

from argus_cli.repl.completions import refresh_completions
from argus_cli.repl.state import ReplState, ensure_history_dir


def show_banner(console: Console, state: ReplState) -> None:
    """Show ASCII banner and connection summary on REPL startup."""
    from argus_cli import __version__
    from argus_cli.widgets.banner import render_banner

    render_banner(version=__version__, server_url=state.config.server_url)
    console.print()

    conn = state.connection
    if conn.is_connected:
        summary_parts = ["[success]Connected[/]"]
        if conn.version:
            summary_parts.append(f"v{conn.version}")
        if conn.uptime:
            summary_parts.append(f"uptime {conn.uptime}")
        summary_parts.append(f"{conn.healthy_count}/{conn.backend_count} backends healthy")
        console.print("  " + " \u00b7 ".join(summary_parts))
    else:
        console.print("  [warning]Not connected[/] \u2014 some commands may not work")

    console.print("  [muted]Type 'help' for usage, 'exit' to quit.[/]")
    console.print()


def show_help(console: Console) -> None:
    """Show REPL help text."""
    help_text = """\
[argus.header]Commands[/]

  [argus.key]server[/]       Server lifecycle (start, stop, status)
  [argus.key]backends[/]     Backend management (list, inspect, reconnect)
  [argus.key]tools[/]        MCP tools (list, inspect, call)
  [argus.key]resources[/]    MCP resources (list, read)
  [argus.key]prompts[/]      MCP prompts (list, get)
  [argus.key]registry[/]     Server registry (search, install)
  [argus.key]config[/]       Configuration (show, validate, reload)
  [argus.key]secrets[/]      Secrets management (list, set, get, delete)
  [argus.key]auth[/]         Authentication (status, configure, test)
  [argus.key]health[/]       Health & sessions (status, sessions)
  [argus.key]audit[/]        Audit log (list, export)
  [argus.key]events[/]       Events (list, stream)
  [argus.key]skills[/]       Skills (list, enable, disable)
  [argus.key]workflows[/]    Workflows (list, run, history)
  [argus.key]operations[/]   Optimizer & telemetry
  [argus.key]batch[/]        Bulk operations

[argus.header]REPL Commands[/]

  [argus.key]use backend[/]  <name|none> \u2014 scope all commands to a backend
  [argus.key]alias[/]        name=command \u2014 create session alias
  [argus.key]unalias[/]      <name> \u2014 remove alias
  [argus.key]watch[/]        [--interval N] <command> \u2014 auto-refresh
  [argus.key]connect[/]      <url> \u2014 switch server connection
  [argus.key]set[/]          <key> <value> \u2014 change settings (output, no-color)
  [argus.key]clear[/]        Clear screen
  [argus.key]history[/]      Show command history
  [argus.key]help[/]         Show this help
  [argus.key]exit[/]         Exit the REPL

[muted]Tip: Use $_ to reference the last command\u2019s result as JSON.[/]"""
    console.print(help_text)


def handle_use(console: Console, state: ReplState, args: list[str]) -> None:
    """Handle 'use backend <name>' context switching."""
    if len(args) >= 2 and args[0] == "backend":
        name = args[1]
        if name in ("none", ""):
            state.session.scoped_backend = None
            console.print("  [info]Backend scope cleared.[/]")
        elif name in state.completions.backend_names:
            state.session.scoped_backend = name
            console.print(f"  [info]Scoped to backend:[/] [bold]{name}[/]")
        else:
            console.print(f"  [warning]Unknown backend:[/] {name}")
            if state.completions.backend_names:
                console.print(
                    f"  [muted]Available: {', '.join(state.completions.backend_names)}[/]"
                )
        return
    console.print("  [muted]Usage: use backend <name|none>[/]")


def handle_alias(console: Console, state: ReplState, args: list[str]) -> None:
    """Handle alias creation/listing: ``alias ll=backends list``."""
    if not args:
        if not state.session.aliases:
            console.print("  [muted]No aliases defined.[/]")
        else:
            for name, cmd in state.session.aliases.items():
                console.print(f"  [argus.key]{name}[/] = [argus.value]{cmd}[/]")
        return

    text = " ".join(args)
    if "=" in text:
        name, _, value = text.partition("=")
        name = name.strip()
        value = value.strip().strip("'\"")
        if name and value:
            state.session.aliases[name] = value
            console.print(f"  [success]Alias set:[/] {name} = {value}")
            return
    console.print("  [muted]Usage: alias name=command[/]")


def handle_unalias(console: Console, state: ReplState, args: list[str]) -> None:
    """Remove an alias."""
    if not args:
        console.print("  [muted]Usage: unalias <name>[/]")
        return
    name = args[0]
    if name in state.session.aliases:
        del state.session.aliases[name]
        console.print(f"  [success]Alias removed:[/] {name}")
    else:
        console.print(f"  [warning]No alias:[/] {name}")


def handle_watch(
    console: Console,
    state: ReplState,
    args: list[str],
    dispatch_fn: object,
) -> None:
    """Handle ``watch [--interval N] <command>`` — auto-refresh."""
    if not args:
        console.print("  [muted]Usage: watch [--interval N] <command>[/]")
        return

    interval = 2
    cmd_args = list(args)
    if cmd_args[0] == "--interval" and len(cmd_args) >= 2:
        try:
            interval = max(1, int(cmd_args[1]))
        except ValueError:
            console.print("  [error]Invalid interval[/]")
            return
        cmd_args = cmd_args[2:]

    if not cmd_args:
        console.print("  [muted]Usage: watch [--interval N] <command>[/]")
        return

    cmd_text = " ".join(cmd_args)
    console.print(f"  [info]Watching:[/] {cmd_text} (every {interval}s, Ctrl-C to stop)")

    try:
        while True:
            console.clear()
            console.print(f"  [muted]watch: {cmd_text} (every {interval}s, Ctrl-C to stop)[/]\n")
            dispatch_fn(console, state, cmd_text)  # type: ignore[operator]
            _time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n  [muted]Watch stopped.[/]")


def handle_connect(console: Console, state: ReplState, args: list[str]) -> None:
    """Handle ``connect <url>`` — change server and reconnect."""
    if not args:
        console.print(f"  [info]Current server:[/] {state.config.server_url}")
        return

    url = args[0]
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        console.print("  [error]Only http/https URLs are supported.[/]")
        return
    state.config.server_url = url
    console.print(f"  [info]Connecting to:[/] {url}")
    refresh_completions(state)
    conn = state.connection
    if conn.is_connected:
        console.print(
            f"  [success]Connected[/] \u2014 {conn.healthy_count}/{conn.backend_count} backends"
        )
    else:
        console.print("  [error]Connection failed[/]")


def handle_set(console: Console, state: ReplState, args: list[str]) -> None:
    """Handle ``set <key> <value>`` — change REPL settings."""
    if len(args) < 2:
        console.print("  [muted]Usage: set <key> <value>[/]")
        console.print("  [muted]Keys: output, no-color, theme, show-toolbar, vi-mode[/]")
        return

    key, value = args[0], args[1]
    _bool = value.lower() in ("true", "1", "yes")

    if key == "output":
        if value in ("rich", "json", "table", "text"):
            state.config.output_format = value
            console.print(f"  [success]Output format set to:[/] {value}")
        else:
            console.print(f"  [error]Invalid format:[/] {value}")
    elif key == "no-color":
        state.config.no_color = _bool
        console.print(f"  [success]No-color set to:[/] {state.config.no_color}")
    elif key == "theme":
        from argus_cli.theme import THEME_NAMES, set_active_theme

        if set_active_theme(value):
            state.config.theme = value
            console.print(f"  [success]Theme set to:[/] {value}")
        else:
            names = ", ".join(THEME_NAMES)
            console.print(f"  [error]Unknown theme:[/] {value}")
            console.print(f"  [muted]Available: {names}[/]")
    elif key == "show-toolbar":
        state.config.show_toolbar = _bool
        console.print(f"  [success]Toolbar set to:[/] {state.config.show_toolbar}")
    elif key == "vi-mode":
        state.config.vi_mode = _bool
        console.print(f"  [success]Vi-mode set to:[/] {state.config.vi_mode}")
        console.print("  [muted]Restart the REPL for key-binding changes to take effect.[/]")
    else:
        console.print(f"  [warning]Unknown setting:[/] {key}")


def handle_history(console: Console, limit: int = 50) -> None:
    """Show recent command history from the history file."""
    history_path = ensure_history_dir()
    try:
        content = Path(history_path).read_text(encoding="utf-8")
        lines = [line for line in content.strip().splitlines() if line.startswith("+")]
        recent = lines[-limit:] if len(lines) > limit else lines
        for i, line in enumerate(recent, 1):
            cmd = line.lstrip("+").strip()
            console.print(f"  [muted]{i:>3}[/]  {cmd}")
        if not recent:
            console.print("  [muted]No history yet.[/]")
    except FileNotFoundError:
        console.print("  [muted]No history yet.[/]")
