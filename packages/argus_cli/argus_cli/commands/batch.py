"""Batch commands — reconnect-all, restart-all."""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


@app.command("reconnect-all")
def reconnect_all(
    ctx: typer.Context,
    confirm: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Reconnect all backends."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import get_console, print_error, print_success
    from argus_cli.theme import status_markup

    if not confirm:
        proceed = typer.confirm("Reconnect all backends?")
        if not proceed:
            raise typer.Abort()

    cfg = ctx.obj
    console = get_console()

    try:
        with ArgusClient(cfg) as client:
            backends_data = client.backends()
        backends = backends_data.get("backends", [])
    except ArgusClientError as e:
        print_error(f"Failed to list backends: {e.message}")
        raise typer.Exit(1) from None

    if not backends:
        print_error("No backends found.")
        raise typer.Exit(1) from None

    console.print(f"[argus.header]Reconnecting {len(backends)} backend(s)...[/]\n")
    success_count = 0
    fail_count = 0

    from rich.progress import Progress, SpinnerColumn, TextColumn

    with (
        Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress,
        ArgusClient(cfg) as client,
    ):
        task = progress.add_task("Reconnecting...", total=len(backends))
        for b in backends:
            name = b.get("name", "unknown")
            progress.update(task, description=f"Reconnecting {name}...")
            try:
                result = client.reconnect(name)
                reconnected = result.get("reconnected", False)
                if reconnected:
                    progress.console.print(f"  {status_markup('connected')} {name}")
                    success_count += 1
                else:
                    err = result.get("error", "unknown error")
                    progress.console.print(f"  {status_markup('error')} {name}: {err}")
                    fail_count += 1
            except ArgusClientError as e:
                progress.console.print(f"  {status_markup('error')} {name}: {e.message}")
                fail_count += 1
            progress.advance(task)

    console.print()
    print_success(f"Reconnect complete: {success_count} succeeded, {fail_count} failed.")
    if fail_count > 0:
        raise typer.Exit(1) from None


@app.command("restart-all")
def restart_all(
    ctx: typer.Context,
    confirm: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
    output_fmt: OutputOption = None,
) -> None:
    """Restart all backends (reload configuration)."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, print_success

    if not confirm:
        proceed = typer.confirm("Restart all backends? This will reload the configuration.")
        if not proceed:
            raise typer.Abort()

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.reload()
    except ArgusClientError as e:
        print_error(f"Restart failed: {e.message}")
        raise typer.Exit(1) from None

    reloaded = data.get("reloaded", False)
    if reloaded:
        info = {
            "reloaded": str(reloaded),
            "backends_added": data.get("backends_added", 0),
            "backends_removed": data.get("backends_removed", 0),
            "backends_changed": data.get("backends_changed", 0),
        }
        errors = data.get("errors", [])
        if errors:
            info["errors"] = ", ".join(errors)
        output(info, fmt=cfg.output_format, spec=OutputSpec(title="Restart Result"))
        print_success("All backends restarted successfully.")
    else:
        errors = data.get("errors", [])
        print_error(f"Restart failed: {', '.join(errors) if errors else 'unknown error'}")
        raise typer.Exit(1) from None
