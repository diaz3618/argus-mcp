"""Events commands — list, stream (SSE)."""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_events(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option(help="Maximum events to return.")] = 100,
    severity: Annotated[
        str | None, typer.Option(help="Filter by severity: debug, info, warning, error.")
    ] = None,
    search: Annotated[str | None, typer.Option(help="Search pattern in messages.")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """List recent events."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    config = ctx.obj
    try:
        with ArgusClient(config) as client:
            data = client.events(limit=limit, severity=severity)
        events = data.get("events", data)

        if search:
            q = search.lower()
            events = [e for e in events if q in str(e.get("message", "")).lower()]

        output(
            events,
            fmt=config.output_format,
            spec=OutputSpec(
                title="Events",
                columns=["timestamp", "stage", "severity", "message"],
                key_field="severity",
            ),
        )
    except ArgusClientError as e:
        print_error(f"Failed to list events: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def stream(
    ctx: typer.Context,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow live events.")] = True,
) -> None:
    """Stream live events via SSE (new, beyond TUI)."""
    import asyncio

    from argus_cli.output import get_console

    config = ctx.obj
    console = get_console()

    async def _stream() -> None:
        from argus_cli.client import ArgusClientError, AsyncArgusClient

        console.print("[info]Connecting to event stream...[/]")
        try:
            async with AsyncArgusClient(config) as client:
                console.print("[success]Connected.[/] Press Ctrl+C to stop.\n")
                async for event in client.events_stream():
                    event_type = event.get("event", "unknown")
                    data = event.get("data", {})
                    if isinstance(data, dict):
                        severity = data.get("severity", "info")
                        message = data.get("message", str(data))
                    else:
                        severity = "info"
                        message = str(data)
                    console.print(f"[muted]{event_type}[/] [{severity}]{message}[/]")
        except ArgusClientError as e:
            console.print(f"[error]Stream error:[/] {e.message}")
        except KeyboardInterrupt:
            console.print("\n[muted]Stream stopped.[/]")

    try:
        asyncio.run(_stream())
    except KeyboardInterrupt:
        console.print("\n[muted]Stream stopped.[/]")
