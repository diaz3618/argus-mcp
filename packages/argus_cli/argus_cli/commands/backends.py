"""Backend management commands — list, inspect, reconnect, health, groups, sessions."""

from __future__ import annotations

__all__ = ["app"]

from typing import TYPE_CHECKING, Annotated, Any

import typer

from argus_cli.output import OutputOption

if TYPE_CHECKING:
    from rich.console import Console

app = typer.Typer(no_args_is_help=True)


def _flatten_backend(b: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested BackendDetail fields for table display."""
    caps = b.get("capabilities", {})
    health = b.get("health", {})
    return {
        "name": b.get("name", ""),
        "type": b.get("type", ""),
        "group": b.get("group", ""),
        "phase": b.get("phase", ""),
        "state": b.get("state", ""),
        "tools": caps.get("tools", 0) if isinstance(caps, dict) else 0,
        "resources": caps.get("resources", 0) if isinstance(caps, dict) else 0,
        "prompts": caps.get("prompts", 0) if isinstance(caps, dict) else 0,
        "health": health.get("status", "") if isinstance(health, dict) else "",
        "latency_ms": health.get("latency_ms", "") if isinstance(health, dict) else "",
    }


@app.command("list")
def list_backends(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """List all configured backends with status."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.backends()
        backends = data.get("backends", [])
        rows = [_flatten_backend(b) for b in backends]
        output(
            rows,
            fmt=cfg.output_format,
            spec=OutputSpec(
                title="Backends",
                columns=[
                    "name",
                    "type",
                    "group",
                    "phase",
                    "state",
                    "tools",
                    "resources",
                    "prompts",
                    "health",
                    "latency_ms",
                ],
                key_field="state",
            ),
        )
    except ArgusClientError as e:
        print_error(f"Failed to list backends: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def inspect(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Backend name to inspect.")],
    output_fmt: OutputOption = None,
) -> None:
    """Show detailed information about a specific backend."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.backends()
        backends = data.get("backends", [])
        match = next((b for b in backends if b.get("name") == name), None)
        if match is None:
            print_error(f"Backend '{name}' not found.")
            raise typer.Exit(1) from None
        if cfg.output_format == "rich":
            _render_backend_detail(get_console(), match)
        else:
            output(match, fmt=cfg.output_format, spec=OutputSpec(title=f"Backend: {name}"))
    except ArgusClientError as e:
        print_error(f"Failed to inspect backend: {e.message}")
        raise typer.Exit(1) from None


def _render_info_panel(console: Console, b: dict[str, Any]) -> None:
    """Render the main backend info panel."""
    from rich.panel import Panel

    from argus_cli.theme import COLORS, status_markup

    lines = [
        f"[argus.key]Name:[/]         [argus.value]{b.get('name', 'N/A')}[/]",
        f"[argus.key]Type:[/]         [argus.value]{b.get('type', 'N/A')}[/]",
        f"[argus.key]Group:[/]        [argus.value]{b.get('group', 'N/A')}[/]",
        f"[argus.key]Phase:[/]        {status_markup(str(b.get('phase', 'unknown')))}",
        f"[argus.key]State:[/]        {status_markup(str(b.get('state', 'unknown')))}",
        f"[argus.key]Connected:[/]    [argus.value]{b.get('connected_at') or 'N/A'}[/]",
    ]
    if b.get("error"):
        lines.append(f"[argus.key]Error:[/]        [error]{b['error']}[/]")

    console.print(
        Panel("\n".join(lines), title=f"Backend: {b.get('name', '')}", border_style=COLORS["info"])
    )


def _render_capabilities_panel(console: Console, caps: dict[str, Any]) -> None:
    """Render the capabilities panel."""
    from rich.panel import Panel

    from argus_cli.theme import COLORS

    cap_lines = [
        f"[argus.key]Tools:[/]     [argus.value]{caps.get('tools', 0)}[/]",
        f"[argus.key]Resources:[/] [argus.value]{caps.get('resources', 0)}[/]",
        f"[argus.key]Prompts:[/]   [argus.value]{caps.get('prompts', 0)}[/]",
    ]
    console.print(
        Panel("\n".join(cap_lines), title="Capabilities", border_style=COLORS["highlight"])
    )


def _render_health_panel(console: Console, health: dict[str, Any]) -> None:
    """Render the health panel."""
    from rich.panel import Panel

    from argus_cli.theme import COLORS, status_markup

    latency_raw = health.get("latency_ms")
    latency_display = f"{latency_raw}ms" if latency_raw is not None else "N/A"
    health_lines = [
        f"[argus.key]Status:[/]     {status_markup(str(health.get('status', 'unknown')))}",
        f"[argus.key]Last Check:[/] [argus.value]{health.get('last_check') or 'N/A'}[/]",
        f"[argus.key]Latency:[/]    [argus.value]{latency_display}[/]",
    ]
    console.print(Panel("\n".join(health_lines), title="Health", border_style=COLORS["success"]))


def _render_conditions_table(console: Console, conditions: list[Any]) -> None:
    """Render the conditions table."""
    from rich import box
    from rich.table import Table

    from argus_cli.theme import COLORS

    table = Table(box=box.SIMPLE, title="Conditions")
    table.add_column("Timestamp", style=COLORS["text"])
    table.add_column("Type", style=COLORS["text"])
    table.add_column("Status", style=COLORS["text"])
    table.add_column("Message", style=COLORS["text"])
    for c in conditions:
        if isinstance(c, dict):
            table.add_row(
                str(c.get("timestamp", "")),
                str(c.get("type", "")),
                str(c.get("status", "")),
                str(c.get("message", "")),
            )
        else:
            table.add_row(str(c), "", "", "")
    console.print(table)


def _render_backend_detail(console: Console, b: dict[str, Any]) -> None:
    """Render full BackendDetail as Rich panels."""
    from rich.panel import Panel

    from argus_cli.theme import COLORS

    caps = b.get("capabilities", {})
    health = b.get("health", {})
    conditions = b.get("conditions", [])
    labels = b.get("labels", {})

    _render_info_panel(console, b)

    if isinstance(caps, dict):
        _render_capabilities_panel(console, caps)

    if isinstance(health, dict):
        _render_health_panel(console, health)

    if conditions:
        _render_conditions_table(console, conditions)

    if labels:
        label_lines = [f"[argus.key]{k}:[/] [argus.value]{v}[/]" for k, v in labels.items()]
        console.print(Panel("\n".join(label_lines), title="Labels", border_style=COLORS["overlay"]))


@app.command()
def reconnect(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Backend name to reconnect.")],
) -> None:
    """Reconnect a specific backend."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_success, print_warning

    cfg = ctx.obj
    try:
        from argus_cli.output import get_console

        with get_console().status(f"Reconnecting '{name}'..."), ArgusClient(cfg) as client:
            result = client.reconnect(name)
        if result.get("reconnected"):
            print_success(f"Backend '{name}' reconnected.")
        else:
            err = result.get("error", "unknown reason")
            print_warning(f"Backend '{name}' reconnect response: {err}")
    except ArgusClientError as e:
        print_error(f"Failed to reconnect '{name}': {e.message}")
        raise typer.Exit(1) from None


@app.command("reconnect-all")
def reconnect_all(ctx: typer.Context) -> None:
    """Reconnect all backends."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_info, print_success, print_warning

    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.backends()
        backends = data.get("backends", [])
        if not backends:
            print_info("No backends configured.")
            return

        success = 0
        failed = 0
        with ArgusClient(cfg) as client:
            for b in backends:
                bname = b.get("name", "")
                try:
                    result = client.reconnect(bname)
                    if result.get("reconnected"):
                        print_success(f"  {bname}: reconnected")
                        success += 1
                    else:
                        print_warning(f"  {bname}: {result.get('error', 'failed')}")
                        failed += 1
                except ArgusClientError:
                    print_error(f"  {bname}: error")
                    failed += 1

        print_info(f"Reconnected {success}/{success + failed} backends.")
    except ArgusClientError as e:
        print_error(f"Failed to list backends: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def health(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show health status per backend with circuit breaker state."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.backends()
        backends = data.get("backends", [])
        rows = []
        for b in backends:
            h = b.get("health", {})
            rows.append(
                {
                    "name": b.get("name", ""),
                    "state": b.get("state", ""),
                    "health": h.get("status", "") if isinstance(h, dict) else "",
                    "latency_ms": h.get("latency_ms", "") if isinstance(h, dict) else "",
                    "last_check": h.get("last_check", "") if isinstance(h, dict) else "",
                }
            )
        output(
            rows,
            fmt=cfg.output_format,
            spec=OutputSpec(
                title="Backend Health",
                columns=["name", "state", "health", "latency_ms", "last_check"],
                key_field="health",
            ),
        )
    except ArgusClientError as e:
        print_error(f"Failed to get health: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def groups(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show backend grouping configuration."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.groups()
        output(data, fmt=cfg.output_format, spec=OutputSpec(title="Backend Groups"))
    except ArgusClientError as e:
        print_error(f"Failed to get groups: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def sessions(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show active sessions."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.sessions()
        sessions_list = data.get("sessions", [])
        output(
            sessions_list,
            fmt=cfg.output_format,
            spec=OutputSpec(
                title=f"Active Sessions ({data.get('active_sessions', len(sessions_list))})",
                columns=[
                    "id",
                    "transport_type",
                    "tool_count",
                    "age_seconds",
                    "idle_seconds",
                    "expired",
                ],
                key_field="expired",
            ),
        )
    except ArgusClientError as e:
        print_error(f"Failed to get sessions: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def versions(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show version information for all backends."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.status()
        svc = data.get("service", {})
        output(
            {"name": svc.get("name", "N/A"), "version": svc.get("version", "N/A")},
            fmt=cfg.output_format,
            spec=OutputSpec(title="Version"),
        )
    except ArgusClientError as e:
        print_error(f"Failed to get versions: {e.message}")
        raise typer.Exit(1) from None
