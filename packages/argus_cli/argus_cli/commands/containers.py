"""Container management commands — list, logs, stats, inspect, lifecycle."""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


# Helpers


def _run_async(coro):
    """Run an async coroutine, handling KeyboardInterrupt gracefully."""
    import asyncio
    import contextlib

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(coro)


# Commands


@app.command("list")
def list_containers(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """List all Argus-managed containers with status and resource usage."""
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)

    async def _list() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                data = await client.list_containers()
        except DaemonError as e:
            print_error(f"Failed to list containers: {e.message}")
            raise typer.Exit(1) from None

        containers = data if isinstance(data, list) else data.get("containers", [])
        rows = []
        for c in containers:
            rows.append(
                {
                    "name": c.get(
                        "name", c.get("Names", [""])[0] if isinstance(c.get("Names"), list) else ""
                    ),
                    "id": c.get("id", c.get("Id", ""))[:12],
                    "status": c.get("status", c.get("Status", "")),
                    "image": c.get("image", c.get("Image", "")),
                    "state": c.get("state", c.get("State", "")),
                    "uptime": c.get("uptime", ""),
                }
            )
        output(
            rows,
            fmt=ctx.obj.output_format,
            spec=OutputSpec(
                title="Containers",
                columns=["name", "id", "status", "image", "state", "uptime"],
                key_field="state",
            ),
        )

    _run_async(_list())


@app.command()
def inspect(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
    output_fmt: OutputOption = None,
) -> None:
    """Show detailed information about a container."""
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)

    async def _inspect() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                data = await client.inspect_container(name)
        except DaemonError as e:
            print_error(f"Failed to inspect container '{name}': {e.message}")
            raise typer.Exit(1) from None

        output(
            data,
            fmt=ctx.obj.output_format,
            spec=OutputSpec(title=f"Container: {name}"),
        )

    _run_async(_inspect())


@app.command()
def logs(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output.")] = False,
    since: Annotated[
        str | None, typer.Option(help="Show logs since timestamp (e.g. 2024-01-01T00:00:00).")
    ] = None,
    tail: Annotated[
        str | None, typer.Option(help="Number of lines to show from end (default: all).")
    ] = None,
) -> None:
    """Stream container logs with severity coloring."""
    from argus_cli.output import get_console

    console = get_console()

    _severity_styles = {
        "error": "bold red",
        "err": "bold red",
        "fatal": "bold red",
        "warn": "yellow",
        "warning": "yellow",
        "info": "cyan",
        "debug": "dim",
    }

    def _style_line(line: str) -> str:
        lower = line.lower()
        for keyword, style in _severity_styles.items():
            if keyword in lower:
                return f"[{style}]{line}[/]"
        return line

    async def _logs() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                console.print(
                    f"[dim]Streaming logs for [bold]{name}[/bold]… Press Ctrl+C to stop.[/]\n"
                )
                async for event in client.stream_logs(
                    name,
                    tail=tail,
                    since=since,
                ):
                    data = event.get("data", {})
                    if isinstance(data, dict):
                        line = data.get("line", data.get("message", str(data)))
                    else:
                        line = str(data)
                    console.print(_style_line(line))
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None
        except KeyboardInterrupt:
            console.print("\n[dim]Log stream stopped.[/]")

    _run_async(_logs())


@app.command()
def stats(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
    live: Annotated[
        bool, typer.Option("--live", "-l", help="Live updating display (Ctrl+C to stop).")
    ] = False,
    output_fmt: OutputOption = None,
) -> None:
    """Show container resource usage.

    Without --live, prints a single snapshot.
    With --live, continuously updates in-place like `docker stats`.
    """
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    console = get_console()

    def _make_bar(percent: float, width: int = 30) -> str:
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"{bar} {percent:5.1f}%"

    async def _stats_snapshot() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                async for event in client.stream_stats(name):
                    data = event.get("data", {})
                    info = {
                        "container": name,
                        "cpu_percent": f"{data.get('cpu_percent', 0):.1f}%",
                        "memory_usage": data.get("memory_usage", "N/A"),
                        "memory_limit": data.get("memory_limit", "N/A"),
                        "memory_percent": f"{data.get('memory_percent', 0):.1f}%",
                        "net_rx": data.get("net_rx", "N/A"),
                        "net_tx": data.get("net_tx", "N/A"),
                        "pids": str(data.get("pids", "N/A")),
                    }
                    output(
                        info,
                        fmt=ctx.obj.output_format,
                        spec=OutputSpec(title=f"Stats: {name}"),
                    )
                    break  # single snapshot
        except DaemonError as e:
            print_error(f"Failed to get stats for '{name}': {e.message}")
            raise typer.Exit(1) from None

    async def _stats_live() -> None:
        from rich.live import Live
        from rich.table import Table

        from argus_cli.daemon_client import DaemonClient, DaemonError

        def _build_table(data: dict) -> Table:
            tbl = Table(title=f"Stats: {name}", show_header=False, expand=True)
            tbl.add_column("Metric", style="bold cyan", width=16)
            tbl.add_column("Value")
            cpu = data.get("cpu_percent", 0)
            mem = data.get("memory_percent", 0)
            tbl.add_row("CPU", _make_bar(cpu))
            tbl.add_row("Memory", _make_bar(mem))
            tbl.add_row(
                "Mem Usage",
                f"{data.get('memory_usage', 'N/A')} / {data.get('memory_limit', 'N/A')}",
            )
            tbl.add_row("Net I/O", f"↓ {data.get('net_rx', 'N/A')}  ↑ {data.get('net_tx', 'N/A')}")
            tbl.add_row("PIDs", str(data.get("pids", "N/A")))
            return tbl

        try:
            async with DaemonClient() as client:
                console.print(
                    f"[dim]Live stats for [bold]{name}[/bold]… Press Ctrl+C to stop.[/]\n"
                )
                with Live(console=console, refresh_per_second=2) as live_display:
                    async for event in client.stream_stats(name):
                        data = event.get("data", {})
                        live_display.update(_build_table(data))
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None
        except KeyboardInterrupt:
            console.print("\n[dim]Live stats stopped.[/]")

    if live:
        _run_async(_stats_live())
    else:
        _run_async(_stats_snapshot())


@app.command()
def start(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
) -> None:
    """Start a stopped container."""
    from argus_cli.output import get_console

    console = get_console()

    async def _start() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                await client.start_container(name)
            console.print(f"[green]✓[/] Container [bold]{name}[/] started.")
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None

    _run_async(_start())


@app.command()
def stop(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation.")] = False,
) -> None:
    """Stop a running container."""
    from argus_cli.output import get_console

    console = get_console()
    if not force:
        confirm = typer.confirm(f"Stop container '{name}'?")
        if not confirm:
            raise typer.Abort()

    async def _stop() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                await client.stop_container(name)
            console.print(f"[green]✓[/] Container [bold]{name}[/] stopped.")
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None

    _run_async(_stop())


@app.command()
def restart(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation.")] = False,
) -> None:
    """Restart a container."""
    from argus_cli.output import get_console

    console = get_console()
    if not force:
        confirm = typer.confirm(f"Restart container '{name}'?")
        if not confirm:
            raise typer.Abort()

    async def _restart() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                await client.restart_container(name)
            console.print(f"[green]✓[/] Container [bold]{name}[/] restarted.")
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None

    _run_async(_restart())


@app.command()
def remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation.")] = False,
) -> None:
    """Remove a container."""
    from argus_cli.output import get_console

    console = get_console()
    if not force:
        confirm = typer.confirm(f"Remove container '{name}'? This cannot be undone.")
        if not confirm:
            raise typer.Abort()

    async def _remove() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                await client.remove_container(name)
            console.print(f"[green]✓[/] Container [bold]{name}[/] removed.")
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None

    _run_async(_remove())


@app.command()
def exec(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Container name or ID.")],
    command: Annotated[list[str], typer.Argument(help="Command to execute.")],
) -> None:
    """Execute a command inside a running container.

    .. warning:: Not yet supported by argusd. This is a placeholder.
    """
    from argus_cli.output import print_error

    print_error(
        f"[stub] 'containers exec {name}' is not yet supported by the argusd daemon. "
        "Use 'docker exec' directly for now."
    )
    raise typer.Exit(1)
