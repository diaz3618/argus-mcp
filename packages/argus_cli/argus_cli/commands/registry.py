"""Registry commands — search, inspect, install.

Queries the Argus management API for backend and capability information,
presenting them as a browsable registry of available MCP servers.
"""

from __future__ import annotations

__all__ = ["app"]

from typing import TYPE_CHECKING, Annotated, Any

import typer

from argus_cli.output import OutputOption

if TYPE_CHECKING:
    from rich.console import Console

app = typer.Typer(no_args_is_help=True)


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str | None, typer.Argument(help="Search query (filters by name).")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """Search the MCP server registry (backends + capabilities)."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.backends()
        backends = data.get("backends", [])

        if query:
            q = query.lower()
            backends = [
                b
                for b in backends
                if q in b.get("name", "").lower() or q in b.get("type", "").lower()
            ]

        if not backends:
            print_info("No registry entries found.")
            return

        rows = []
        for b in backends:
            caps = b.get("capabilities", {})
            rows.append(
                {
                    "name": b.get("name", ""),
                    "type": b.get("type", ""),
                    "group": b.get("group", ""),
                    "state": b.get("state", ""),
                    "tools": caps.get("tools", 0) if isinstance(caps, dict) else 0,
                    "resources": caps.get("resources", 0) if isinstance(caps, dict) else 0,
                    "prompts": caps.get("prompts", 0) if isinstance(caps, dict) else 0,
                }
            )
        output(
            rows,
            fmt=cfg.output_format,
            spec=OutputSpec(
                title="Registry",
                columns=["name", "type", "group", "state", "tools", "resources", "prompts"],
                key_field="state",
            ),
        )
    except ArgusClientError as e:
        print_error(f"Failed to search registry: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def inspect(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Registry entry name (backend name).")],
    output_fmt: OutputOption = None,
) -> None:
    """Inspect a registry entry — show full backend details and capabilities."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            bd = client.backends()
            caps = client.capabilities(backend=name)

        backends = bd.get("backends", [])
        match = next((b for b in backends if b.get("name") == name), None)
        if match is None:
            print_error(f"Registry entry '{name}' not found.")
            raise typer.Exit(1) from None

        if cfg.output_format == "rich":
            _render_registry_detail(get_console(), match, caps)
        else:
            match["available_tools"] = [t.get("name", "") for t in caps.get("tools", [])]
            match["available_resources"] = [r.get("uri", "") for r in caps.get("resources", [])]
            match["available_prompts"] = [p.get("name", "") for p in caps.get("prompts", [])]
            output(match, fmt=cfg.output_format, spec=OutputSpec(title=f"Registry: {name}"))
    except ArgusClientError as e:
        print_error(f"Failed to inspect registry entry: {e.message}")
        raise typer.Exit(1) from None


def _render_registry_detail(
    console: Console, backend: dict[str, Any], caps: dict[str, Any]
) -> None:
    """Render a registry entry with Rich panels."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    from argus_cli.theme import COLORS, status_markup

    # Backend identity
    lines = [
        f"[argus.key]Name:[/]    [argus.value]{backend.get('name', 'N/A')}[/]",
        f"[argus.key]Type:[/]    [argus.value]{backend.get('type', 'N/A')}[/]",
        f"[argus.key]Group:[/]   [argus.value]{backend.get('group', 'N/A')}[/]",
        f"[argus.key]State:[/]   {status_markup(str(backend.get('state', 'unknown')))}",
    ]
    c = backend.get("capabilities", {})
    if isinstance(c, dict):
        lines.append(f"[argus.key]Tools:[/]   [argus.value]{c.get('tools', 0)}[/]")
        lines.append(f"[argus.key]Resources:[/] [argus.value]{c.get('resources', 0)}[/]")
        lines.append(f"[argus.key]Prompts:[/] [argus.value]{c.get('prompts', 0)}[/]")
    console.print(
        Panel(
            "\n".join(lines),
            title=f"Registry: {backend.get('name', '')}",
            border_style=COLORS["info"],
        )
    )

    # Tools list
    tools = caps.get("tools", [])
    if tools:
        table = Table(box=box.SIMPLE, title="Tools")
        table.add_column("NAME", style=COLORS["text"])
        table.add_column("DESCRIPTION", style=COLORS["subtext"])
        for t in tools:
            table.add_row(t.get("name", ""), (t.get("description", "") or "")[:80])
        console.print(table)

    # Resources list
    resources = caps.get("resources", [])
    if resources:
        table = Table(box=box.SIMPLE, title="Resources")
        table.add_column("URI", style=COLORS["text"])
        table.add_column("MIME TYPE", style=COLORS["subtext"])
        for r in resources:
            table.add_row(r.get("uri", ""), r.get("mime_type", ""))
        console.print(table)

    # Prompts list
    prompts = caps.get("prompts", [])
    if prompts:
        table = Table(box=box.SIMPLE, title="Prompts")
        table.add_column("NAME", style=COLORS["text"])
        table.add_column("DESCRIPTION", style=COLORS["subtext"])
        for p in prompts:
            table.add_row(p.get("name", ""), (p.get("description", "") or "")[:80])
        console.print(table)


@app.command()
def install(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Backend name to add to config.")],
    backend_type: Annotated[
        str,
        typer.Option("--type", help="Backend type (e.g. stdio, sse, docker)."),
    ] = "stdio",
    command: Annotated[
        str | None,
        typer.Option(
            "--command",
            help="Command to run (for stdio backends).",
            rich_help_panel="Backend Settings",
        ),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option(
            "--url",
            help="Server URL (for sse backends).",
            rich_help_panel="Backend Settings",
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Config file path to update.",
            rich_help_panel="Configuration",
        ),
    ] = None,
    reload_server: Annotated[
        bool,
        typer.Option(
            "--reload/--no-reload",
            help="Reload after install.",
            rich_help_panel="Configuration",
        ),
    ] = True,
) -> None:
    """Install a new MCP server backend into the configuration."""
    import yaml

    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_info, print_success

    cfg = ctx.obj

    # Build backend entry
    entry: dict[str, Any] = {"type": backend_type}
    if command:
        entry["command"] = command
    if url:
        entry["url"] = url

    if config:
        # Append to config file
        config_path = config
        try:
            with open(config_path, encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            config_data = {}

        backends = config_data.setdefault("backends", {})
        if name in backends:
            print_error(f"Backend '{name}' already exists in {config_path}.")
            raise typer.Exit(1) from None
        backends[name] = entry

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)
        print_success(f"Added backend '{name}' to {config_path}.")
    else:
        print_info(f"Backend entry for '{name}': {entry}")
        print_info("Use --config PATH to write to a config file.")
        return

    # Optionally trigger reload
    if reload_server:
        try:
            with ArgusClient(cfg) as client:
                result = client.reload()
            added = result.get("backends_added", 0)
            print_success(f"Server reloaded — {added} backend(s) added.")
        except ArgusClientError as e:
            print_error(f"Config saved but reload failed: {e.message}")
