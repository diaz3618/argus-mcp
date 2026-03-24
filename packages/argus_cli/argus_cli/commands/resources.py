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
    """Read the contents of an MCP resource."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_info

    cfg = ctx.obj
    # Verify resource exists first
    try:
        with ArgusClient(cfg) as client:
            data = client.capabilities(type_filter="resources")
        resources = data.get("resources", [])
        match = next((r for r in resources if r.get("uri") == uri), None)
        if match is None:
            print_error(f"Resource '{uri}' not found.")
            raise typer.Exit(1) from None
        print_info(
            f"Resource '{match.get('name', uri)}' on backend '{match.get('backend', 'unknown')}' "
            f"(mime: {match.get('mime_type', 'unknown')}). "
            "Direct MCP resource reading requires a running MCP session."
        )
        print_info("Use 'argus shell' for interactive resource access.")
    except ArgusClientError as e:
        print_error(f"Failed to read resource: {e.message}")
        raise typer.Exit(1) from None
