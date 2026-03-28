"""Config commands — CLI-local configuration management.

Named ``config_cmd`` to avoid collision with top-level ``config.py``.

CLI-local commands (init, local, themes) live here.
Server-side config operations (show, validate, diff, reload, export)
are in ``config_server.py`` and mounted as sub-commands.
"""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.commands.config_server import app as server_app
from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)

# Merge server-side config commands (show, validate, diff, reload, export)
# into this app so everything appears under the single `config` group.
app.registered_commands.extend(server_app.registered_commands)


_CONFIG_TEMPLATE = """\
# Argus MCP CLI configuration
# Location: ~/.config/argus-mcp/config.yaml
#
# Values here are used as defaults. CLI flags and environment
# variables override them (flags > env / .env > this file > built-in defaults).
#
# You can also place env vars in a .env file in your working directory.

# Argus server URL (env: ARGUS_SERVER_URL | flag: --server / -s)
server_url: "http://127.0.0.1:9000"

# Management API token (env: ARGUS_MGMT_TOKEN | flag: --token / -t)
# token: ""

# Default output format: rich | json | table | text
# When piping stdout, auto-switches to json unless explicitly set.
# env: ARGUS_OUTPUT_FORMAT | flag: --output / -o
output_format: "rich"

# Disable colored output (env: NO_COLOR | flag: --no-color)
no_color: false

# Color theme (flag: --theme).
# Run `argus config themes` for a full list with previews.
theme: "catppuccin-mocha"

# Show the bottom toolbar in the REPL
show_toolbar: true

# Enable vi-mode key bindings in the REPL (default: emacs-style)
vi_mode: false

# Seconds between automatic server-status refreshes (0 = disable)
poll_interval: 30

# Max history entries shown by the `history` command
history_limit: 50

# ── argusd (Docker/Kubernetes sidecar daemon) ──────────────────────
# argusd is required for `argus containers` and `argus pods` commands.
# See: https://github.com/diaz3618/argus-mcp/blob/main/docs/architecture/07-argusd.md
argusd:
  # Automatically start argusd when a container/pod command needs it.
  # When true, the CLI/TUI will spawn argusd in the background if the
  # socket is not already present.
  # env: ARGUSD_AUTO_START
  auto_start: false

  # Path to the argusd binary. Omit to auto-detect ($PATH, then
  # the well-known build location packages/argusd/argusd).
  # env: ARGUSD_BINARY
  # binary: "/usr/local/bin/argusd"

  # Custom Unix Domain Socket path. Omit to use the default:
  # $XDG_RUNTIME_DIR/argusd.sock  (or /tmp/argusd.sock).
  # env: ARGUSD_SOCKET
  # socket: "/run/user/1000/argusd.sock"
"""


@app.command()
def init(
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite existing config file.")
    ] = False,
) -> None:
    """Generate a default CLI config file at ~/.config/argus-mcp/config.yaml."""
    from argus_cli.config import CONFIG_DIR, CONFIG_FILE
    from argus_cli.output import print_error, print_info, print_success

    if CONFIG_FILE.is_file() and not force:
        print_error(f"Config already exists: {CONFIG_FILE}")
        print_info("  Use --force to overwrite.")
        raise typer.Exit(1) from None

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    print_success(f"Config written to {CONFIG_FILE}")


@app.command()
def local(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show the local CLI configuration (resolved values)."""
    from argus_cli.config import CONFIG_FILE
    from argus_cli.output import OutputSpec, apply_output_option, output

    apply_output_option(output_fmt)
    cfg = ctx.obj
    data = {
        "config_file": str(CONFIG_FILE),
        "config_file_exists": CONFIG_FILE.is_file(),
        "server_url": cfg.server_url,
        "token": "***" if cfg.token else None,
        "output_format": cfg.output_format,
        "no_color": cfg.no_color,
        "theme": cfg.theme,
        "show_toolbar": cfg.show_toolbar,
        "vi_mode": cfg.vi_mode,
        "poll_interval": cfg.poll_interval,
        "history_limit": cfg.history_limit,
    }
    output(data, fmt=cfg.output_format, spec=OutputSpec(title="CLI Configuration"))


@app.command()
def themes(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """List all available CLI color themes."""
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output
    from argus_cli.theme import PALETTES, THEME_NAMES, get_active_theme

    apply_output_option(output_fmt)

    cfg = ctx.obj

    if cfg.output_format != "rich":
        data = [{"name": name, "active": name == get_active_theme()} for name in THEME_NAMES]
        output(data, fmt=cfg.output_format, spec=OutputSpec(title="Themes"))
        return

    from rich.table import Table

    table = Table(title="Available Themes", show_lines=False)
    table.add_column("Theme", style="bold")
    table.add_column("Colors", no_wrap=True)
    table.add_column("Active", justify="center")

    active = get_active_theme()
    for name in THEME_NAMES:
        palette = PALETTES[name]
        swatches = " ".join(
            f"[{palette[k]}]\u2588\u2588[/]"
            for k in ("success", "error", "warning", "highlight", "info", "accent")
        )
        marker = "[success]\u2714[/]" if name == active else ""
        table.add_row(name, swatches, marker)

    get_console().print(table)
