"""Audit log commands — list, export."""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_audit(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option(help="Maximum entries to return.")] = 100,
    type_filter: Annotated[str | None, typer.Option("--type", help="Filter by event type.")] = None,
    search: Annotated[str | None, typer.Option(help="Search pattern.")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """List audit log entries."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error

    apply_output_option(output_fmt)
    config = ctx.obj
    try:
        with ArgusClient(config) as client:
            data = client.events(limit=limit, severity=type_filter)
        events = data.get("events", data)

        # Client-side search filter
        if search:
            q = search.lower()
            events = [
                e
                for e in events
                if q in str(e.get("message", "")).lower()
                or q in str(e.get("stage", "")).lower()
                or q in str(e.get("backend", "")).lower()
            ]

        output(
            events,
            fmt=config.output_format,
            spec=OutputSpec(
                title="Audit Log",
                columns=["timestamp", "stage", "severity", "message"],
                key_field="severity",
            ),
        )
    except ArgusClientError as e:
        print_error(f"Failed to get audit log: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def export(
    ctx: typer.Context,
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Export format: json or csv.")
    ] = "json",
    since: Annotated[str | None, typer.Option(help="Export since timestamp (ISO 8601).")] = None,
    limit: Annotated[int, typer.Option(help="Maximum entries to export.")] = 1000,
    output_file: Annotated[
        str | None, typer.Option("--output", "-o", help="Output file (default: stdout).")
    ] = None,
) -> None:
    """Export audit log entries as JSON or CSV."""
    import csv
    import io
    import json
    import sys

    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_success

    config = ctx.obj
    try:
        with ArgusClient(config) as client:
            data = client.events(limit=limit, since=since)
        events = data.get("events", [])
    except ArgusClientError as e:
        print_error(f"Failed to export audit log: {e.message}")
        raise typer.Exit(1) from None

    if fmt == "json":
        content = json.dumps(events, indent=2, default=str)
    elif fmt == "csv":
        if not events:
            content = ""
        else:
            buf = io.StringIO()
            fieldnames = ["id", "timestamp", "stage", "severity", "message", "backend"]
            writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for event in events:
                writer.writerow(event)
            content = buf.getvalue()
    else:
        print_error(f"Unsupported format: {fmt}. Use 'json' or 'csv'.")
        raise typer.Exit(1) from None

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print_success(f"Exported {len(events)} entries to {output_file}.")
    else:
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
