"""Health commands — status, sessions, versions, groups."""

from __future__ import annotations

__all__ = ["app"]

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


@app.command()
def status(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show overall health status."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    config = ctx.obj
    try:
        with ArgusClient(config) as client:
            data = client.health()
    except ArgusClientError as e:
        print_error(f"Failed to get health: {e.message}")
        raise typer.Exit(1) from None

    backends = data.get("backends", {})
    info = {
        "status": data.get("status", "unknown"),
        "uptime": f"{data.get('uptime_seconds', 0):.0f}s",
        "version": data.get("version", "unknown"),
        "backends_total": backends.get("total", 0),
        "backends_connected": backends.get("connected", 0),
        "backends_healthy": backends.get("healthy", 0),
    }
    output(info, fmt=config.output_format, spec=OutputSpec(title="Health Status"))


@app.command()
def sessions(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show active MCP sessions."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    config = ctx.obj
    try:
        with ArgusClient(config) as client:
            data = client.sessions()
    except ArgusClientError as e:
        print_error(f"Failed to get sessions: {e.message}")
        raise typer.Exit(1) from None

    session_list = data.get("sessions", data if isinstance(data, list) else [])
    rows = []
    for s in session_list:
        rows.append(
            {
                "id": s.get("id", ""),
                "transport": s.get("transport_type", ""),
                "tools": s.get("tool_count", 0),
                "age": f"{s.get('age_seconds', 0):.0f}s",
                "idle": f"{s.get('idle_seconds', 0):.0f}s",
                "expired": str(s.get("expired", False)),
            }
        )

    output(
        rows,
        fmt=config.output_format,
        spec=OutputSpec(
            title="Sessions",
            columns=["id", "transport", "tools", "age", "idle", "expired"],
        ),
    )


@app.command()
def versions(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show version information."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    config = ctx.obj
    try:
        with ArgusClient(config) as client:
            data = client.status()
    except ArgusClientError as e:
        print_error(f"Failed to get versions: {e.message}")
        raise typer.Exit(1) from None

    service = data.get("service", {})
    transport = data.get("transport", {})
    info = {
        "name": service.get("name", "unknown"),
        "version": service.get("version", "unknown"),
        "state": service.get("state", "unknown"),
        "uptime": f"{service.get('uptime_seconds', 0):.0f}s",
        "sse_url": transport.get("sse_url", ""),
        "http_url": transport.get("streamable_http_url", ""),
    }
    output(info, fmt=config.output_format, spec=OutputSpec(title="Version Info"))


@app.command()
def groups(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show server groups."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    config = ctx.obj
    try:
        with ArgusClient(config) as client:
            data = client.groups()
    except ArgusClientError as e:
        print_error(f"Failed to get groups: {e.message}")
        raise typer.Exit(1) from None

    groups_list = data.get("groups", data if isinstance(data, list) else [])
    rows = []
    for g in groups_list:
        if isinstance(g, dict):
            rows.append(g)
        else:
            rows.append({"name": str(g)})

    output(
        rows,
        fmt=config.output_format,
        spec=OutputSpec(
            title="Groups",
            columns=["name"] if rows and "name" in rows[0] else None,
        ),
    )
