"""Tools commands — list, inspect, call, rename, filter."""

from __future__ import annotations

__all__ = ["app"]

import json
from typing import TYPE_CHECKING, Annotated, Any

import typer

from argus_cli.output import OutputOption

if TYPE_CHECKING:
    from rich.console import Console

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_tools(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Option(help="Filter by name pattern.")] = None,
    conflicts_only: Annotated[
        bool, typer.Option("--conflicts-only", help="Show only conflicts.")
    ] = False,
    show_filtered: Annotated[
        bool, typer.Option("--show-filtered", help="Include filtered tools.")
    ] = False,
    output_fmt: OutputOption = None,
) -> None:
    """List available MCP tools."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.capabilities(type_filter="tools", search=search)
        tools = data.get("tools", [])
        if conflicts_only:
            # Show tools with name conflicts (original_name != name or renamed)
            tools = [
                t for t in tools if t.get("renamed") or t.get("original_name") != t.get("name")
            ]
        if not show_filtered:
            tools = [t for t in tools if not t.get("filtered")]
        if not tools:
            print_info("No tools found.")
            return
        output(
            tools,
            fmt=cfg.output_format,
            spec=OutputSpec(title="Tools", columns=["name", "backend", "description"]),
        )
    except ArgusClientError as e:
        print_error(f"Failed to list tools: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def inspect(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Tool name to inspect.")],
    output_fmt: OutputOption = None,
) -> None:
    """Show full schema for a specific tool."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.capabilities(type_filter="tools", search=name)
        tools = data.get("tools", [])
        match = next((t for t in tools if t.get("name") == name), None)
        if match is None:
            print_error(f"Tool '{name}' not found.")
            raise typer.Exit(1) from None
        if cfg.output_format == "rich":
            _render_tool_detail(get_console(), match)
        else:
            output(match, fmt=cfg.output_format, spec=OutputSpec(title=f"Tool: {name}"))
    except ArgusClientError as e:
        print_error(f"Failed to inspect tool: {e.message}")
        raise typer.Exit(1) from None


def _render_tool_detail(console: Console, tool: dict[str, Any]) -> None:
    """Render full ToolDetail as Rich panels."""
    from rich.panel import Panel

    from argus_cli.theme import COLORS

    lines = [
        f"[argus.key]Name:[/]          [argus.value]{tool.get('name', 'N/A')}[/]",
        f"[argus.key]Original:[/]      [argus.value]{tool.get('original_name', 'N/A')}[/]",
        f"[argus.key]Backend:[/]       [argus.value]{tool.get('backend', 'N/A')}[/]",
        f"[argus.key]Description:[/]   [argus.value]{tool.get('description', 'N/A')}[/]",
        f"[argus.key]Renamed:[/]       [argus.value]{tool.get('renamed', False)}[/]",
        f"[argus.key]Filtered:[/]      [argus.value]{tool.get('filtered', False)}[/]",
    ]
    console.print(
        Panel("\n".join(lines), title=f"Tool: {tool.get('name', '')}", border_style=COLORS["info"])
    )

    schema = tool.get("input_schema")
    if schema:
        from argus_cli.output import render_json_data

        render_json_data(schema, title="Input Schema")


@app.command()
def call(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Tool name to invoke.")],
    arg: Annotated[
        list[str] | None, typer.Option("--arg", "-a", help="key=value arguments.")
    ] = None,
    raw_json: Annotated[
        str | None, typer.Option("--json", "-j", help="Raw JSON arguments.")
    ] = None,
) -> None:
    """Invoke an MCP tool via the server proxy and display the result."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_info, render_json_data

    cfg = ctx.obj

    # Parse arguments into dict
    arguments: dict[str, Any] = {}
    if raw_json:
        try:
            arguments = json.loads(raw_json)
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON: {e}")
            raise typer.Exit(1) from None
    elif arg:
        for kv in arg:
            if "=" not in kv:
                print_error(f"Invalid argument format '{kv}' — expected key=value.")
                raise typer.Exit(1) from None
            k, v = kv.split("=", 1)
            try:
                arguments[k] = json.loads(v)
            except json.JSONDecodeError:
                arguments[k] = v

    print_info(f"Calling tool '{name}'...")

    try:
        with ArgusClient(cfg) as client:
            result = client.call_tool(name, arguments)
    except ArgusClientError as e:
        print_error(f"Tool call failed: {e.message}")
        raise typer.Exit(1) from None

    if result.get("isError"):
        print_error(f"Tool '{name}' returned an error.")
    else:
        print_info(f"Tool '{name}' on backend '{result.get('backend', 'unknown')}' succeeded.")

    content = result.get("content", [])
    for item in content:
        if item.get("type") == "text":
            render_json_data(item.get("text", ""), title=f"Tool: {name}")
        else:
            render_json_data(item, title=f"Tool: {name}")


@app.command()
def rename(
    name: Annotated[str, typer.Argument(help="Current tool name.")],
    to: Annotated[str, typer.Option("--to", help="New tool name.")],
    description: Annotated[
        str | None, typer.Option("--description", help="New description.")
    ] = None,
) -> None:
    """Rename an MCP tool (requires config reload)."""
    from argus_cli.output import print_info

    print_info(
        f"To rename '{name}' → '{to}', add a rename rule in your config file "
        "under 'tool_rename' and run 'argus config reload'."
    )
    if description:
        print_info(f"Description override: {description}")


@app.command("filter")
def filter_tools(
    allow: Annotated[str | None, typer.Option("--allow", help="Allow glob pattern.")] = None,
    deny: Annotated[str | None, typer.Option("--deny", help="Deny glob pattern.")] = None,
) -> None:
    """Configure tool filtering rules (requires config reload)."""
    from argus_cli.output import print_info, print_warning

    if not allow and not deny:
        print_warning("Specify --allow or --deny glob pattern.")
        raise typer.Exit(1) from None
    if allow:
        print_info(f"To allow tools matching '{allow}', add to config under 'tool_filter.allow'.")
    if deny:
        print_info(f"To deny tools matching '{deny}', add to config under 'tool_filter.deny'.")
    print_info("Then run 'argus config reload' to apply.")
