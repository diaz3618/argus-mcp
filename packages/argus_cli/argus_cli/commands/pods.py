"""Kubernetes pod management commands — list, logs, describe, events, lifecycle."""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


# ── Helpers ────────────────────────────────────────────────────────────


def _run_async(coro):
    """Run an async coroutine, handling KeyboardInterrupt gracefully."""
    import asyncio
    import contextlib

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(coro)


def _parse_pod_ref(name: str) -> tuple[str, str]:
    """Parse 'namespace/name' or assume 'default' namespace."""
    if "/" in name:
        parts = name.split("/", 1)
        return parts[0], parts[1]
    return "default", name


# ── Commands ───────────────────────────────────────────────────────────


@app.command("list")
def list_pods(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """List all Argus-managed Kubernetes pods."""
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)

    async def _list() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                data = await client.list_pods()
        except DaemonError as e:
            print_error(f"Failed to list pods: {e.message}")
            raise typer.Exit(1) from None

        pods = data if isinstance(data, list) else data.get("pods", [])
        rows = []
        for p in pods:
            rows.append(
                {
                    "name": p.get("name", ""),
                    "namespace": p.get("namespace", ""),
                    "status": p.get("status", ""),
                    "node": p.get("node", ""),
                    "ip": p.get("ip", p.get("pod_ip", "")),
                    "restarts": str(p.get("restarts", 0)),
                    "age": p.get("age", ""),
                }
            )
        output(
            rows,
            fmt=ctx.obj.output_format,
            spec=OutputSpec(
                title="Pods",
                columns=["name", "namespace", "status", "node", "ip", "restarts", "age"],
                key_field="status",
            ),
        )

    _run_async(_list())


@app.command()
def describe(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Pod name (or namespace/name).")],
    output_fmt: OutputOption = None,
) -> None:
    """Show detailed information about a Kubernetes pod."""
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    ns, pod_name = _parse_pod_ref(name)

    async def _describe() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                data = await client.describe_pod(ns, pod_name)
        except DaemonError as e:
            print_error(f"Failed to describe pod '{name}': {e.message}")
            raise typer.Exit(1) from None

        output(
            data,
            fmt=ctx.obj.output_format,
            spec=OutputSpec(title=f"Pod: {ns}/{pod_name}"),
        )

    _run_async(_describe())


@app.command()
def logs(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Pod name (or namespace/name).")],
    container: Annotated[
        str | None, typer.Option("--container", "-c", help="Container name within the pod.")
    ] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output.")] = False,
    since: Annotated[
        str | None, typer.Option(help="Show logs since timestamp (e.g. 2024-01-01T00:00:00).")
    ] = None,
    tail: Annotated[str | None, typer.Option(help="Number of lines to show from end.")] = None,
) -> None:
    """Stream Kubernetes pod logs with severity coloring."""
    from argus_cli.output import get_console

    console = get_console()
    ns, pod_name = _parse_pod_ref(name)

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
                    f"[dim]Streaming logs for [bold]{ns}/{pod_name}[/bold]"
                    " … Press Ctrl+C to stop.[/]\n"
                )
                async for event in client.stream_pod_logs(
                    ns,
                    pod_name,
                    container=container,
                    tail=tail,
                    since=since,
                ):
                    data = event.get("data", {})
                    if isinstance(data, dict):
                        line = data.get("line", data.get("message", str(data)))
                    else:
                        line = str(data)
                    console.print(_style_line(line))

                    if not follow:
                        break
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None
        except KeyboardInterrupt:
            console.print("\n[dim]Log stream stopped.[/]")

    _run_async(_logs())


@app.command()
def events(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Pod name (or namespace/name).")],
    output_fmt: OutputOption = None,
) -> None:
    """Show Kubernetes events for a specific pod."""
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    ns, pod_name = _parse_pod_ref(name)

    async def _events() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                data = await client.pod_events(ns, pod_name)
        except DaemonError as e:
            print_error(f"Failed to get events for pod '{name}': {e.message}")
            raise typer.Exit(1) from None

        events_list = data if isinstance(data, list) else data.get("events", [])
        output(
            events_list,
            fmt=ctx.obj.output_format,
            spec=OutputSpec(
                title=f"Events: {ns}/{pod_name}",
                columns=["type", "reason", "message", "age", "count"],
            ),
        )

    _run_async(_events())


@app.command()
def delete(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Pod name (or namespace/name).")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation.")] = False,
) -> None:
    """Delete an Argus-managed Kubernetes pod."""
    from argus_cli.output import get_console

    console = get_console()
    ns, pod_name = _parse_pod_ref(name)

    if not force:
        confirm = typer.confirm(f"Delete pod '{ns}/{pod_name}'?")
        if not confirm:
            raise typer.Abort()

    async def _delete() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                await client.delete_pod(ns, pod_name)
            console.print(f"[green]✓[/] Pod [bold]{ns}/{pod_name}[/] deleted.")
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None

    _run_async(_delete())


@app.command("rollout-restart")
def rollout_restart(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Deployment name (or namespace/name).")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation.")] = False,
) -> None:
    """Trigger a rolling restart of a deployment."""
    from argus_cli.output import get_console

    console = get_console()
    ns, deploy_name = _parse_pod_ref(name)

    if not force:
        confirm = typer.confirm(f"Rollout restart deployment '{ns}/{deploy_name}'?")
        if not confirm:
            raise typer.Abort()

    async def _restart() -> None:
        from argus_cli.daemon_client import DaemonClient, DaemonError

        try:
            async with DaemonClient() as client:
                await client.rollout_restart(ns, deploy_name)
            console.print(
                f"[green]✓[/] Deployment [bold]{ns}/{deploy_name}[/] rollout restart initiated."
            )
        except DaemonError as e:
            console.print(f"[bold red]Error:[/] {e.message}")
            raise typer.Exit(1) from None

    _run_async(_restart())
