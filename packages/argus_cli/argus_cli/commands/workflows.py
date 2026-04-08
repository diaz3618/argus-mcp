"""Workflows commands — list, run, history.

Workflows are sequences of operations (reconnect, reload, tool calls) that
can be defined in config and executed as named presets.
"""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption, OutputSpec

app = typer.Typer(no_args_is_help=True)

# Built-in workflows

BUILTIN_WORKFLOWS = {
    "health-check": {
        "description": "Check health of all backends and report status",
        "steps": ["backends health", "health status"],
    },
    "full-reconnect": {
        "description": "Reconnect all backends and verify health",
        "steps": ["batch reconnect-all --yes", "backends health"],
    },
    "status-report": {
        "description": "Generate a full status report",
        "steps": ["health status", "backends list", "health sessions"],
    },
}


@app.command("list")
def list_workflows(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """List available workflows."""
    from argus_cli.output import apply_output_option, output

    apply_output_option(output_fmt)
    cfg = ctx.obj
    rows = []
    for name, wf in BUILTIN_WORKFLOWS.items():
        rows.append(
            {
                "name": name,
                "description": wf.get("description", ""),
                "steps": len(wf.get("steps", [])),
                "type": "builtin",
            }
        )

    output(
        rows,
        fmt=cfg.output_format,
        spec=OutputSpec(title="Workflows", columns=["name", "description", "steps", "type"]),
    )


@app.command()
def run(
    name: Annotated[str, typer.Argument(help="Workflow name to run.")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview execution plan.")] = False,
) -> None:
    """Run a workflow."""
    from argus_cli.output import get_console, print_error, print_info, print_success

    wf = BUILTIN_WORKFLOWS.get(name)
    if wf is None:
        print_error(
            f"Workflow '{name}' not found. Use 'workflows list' to see available workflows."
        )
        raise typer.Exit(1) from None

    steps = wf.get("steps", [])
    console = get_console()

    if dry_run:
        print_info(f"Workflow '{name}': {wf.get('description', '')}")
        for i, step in enumerate(steps, 1):
            print_info(f"  Step {i}: {step}")
        return

    console.print(f"[argus.header]Running workflow:[/] {name}")
    console.print(f"[muted]{wf.get('description', '')}[/]\n")

    for i, step in enumerate(steps, 1):
        console.print(f"[argus.key]Step {i}:[/] [argus.value]{step}[/]")
        # Execute by invoking the CLI directly via Typer standalone mode
        from argus_cli.main import app as root_app

        try:
            root_app(step.split(), standalone_mode=False)
        except SystemExit as exc:
            if exc.code != 0:
                print_error(f"Step {i} failed (exit code {exc.code}).")
                raise typer.Exit(1) from None

    print_success(f"Workflow '{name}' completed successfully.")


@app.command()
def history(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option(help="Number of entries to show.")] = 20,
    output_fmt: OutputOption = None,
) -> None:
    """Show workflow execution history (from events)."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.events(limit=limit)
        events = data.get("events", [])

        # Filter for workflow-related events
        workflow_events = [
            e
            for e in events
            if "workflow" in str(e.get("message", "")).lower()
            or "workflow" in str(e.get("stage", "")).lower()
        ]

        if not workflow_events:
            print_info("No workflow execution history found in recent events.")
            return

        output(
            workflow_events,
            fmt=cfg.output_format,
            spec=OutputSpec(
                title="Workflow History",
                columns=["timestamp", "stage", "severity", "message"],
                key_field="severity",
            ),
        )
    except ArgusClientError as e:
        print_error(f"Failed to get workflow history: {e.message}")
        raise typer.Exit(1) from None
