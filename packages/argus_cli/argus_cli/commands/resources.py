"""Resources commands — list, read."""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_resources(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Option(help="Filter by name pattern.")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """List available MCP resources."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.capabilities(type_filter="resources", search=search)
        resources = data.get("resources", [])
        if not resources:
            print_info("No resources found.")
            return
        output(
            resources,
            fmt=cfg.output_format,
            spec=OutputSpec(title="Resources", columns=["name", "backend", "uri", "mime_type"]),
        )
    except ArgusClientError as e:
        print_error(f"Failed to list resources: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def read(
    ctx: typer.Context,
    uri: Annotated[str, typer.Argument(help="Resource URI to read.")],
) -> None:
    """Read the contents of an MCP resource via the server proxy."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import get_console, print_error, print_info

    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            result = client.read_resource(uri)
    except ArgusClientError as e:
        print_error(f"Failed to read resource: {e.message}")
        raise typer.Exit(1) from None

    contents = result.get("contents", [])
    if not contents:
        print_info(f"Resource '{uri}' returned no content.")
        return

    console = get_console()
    backend = result.get("backend", "unknown")
    print_info(f"Resource from backend '{backend}':")
    for item in contents:
        text = item.get("text", "")
        mime = item.get("mimeType", "")
        if mime and cfg.output_format == "rich":
            from rich.panel import Panel

            console.print(Panel(text, title=f"{uri} ({mime})", expand=False))
        else:
            console.print(text)
