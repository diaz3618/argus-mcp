"""Prompts commands — list, get."""

from __future__ import annotations

__all__ = ["app"]

from typing import TYPE_CHECKING, Annotated, Any

import typer

from argus_cli.output import OutputOption

if TYPE_CHECKING:
    from rich.console import Console

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_prompts(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Option(help="Filter by name pattern.")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """List available MCP prompts."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.capabilities(type_filter="prompts", search=search)
        prompts = data.get("prompts", [])
        if not prompts:
            print_info("No prompts found.")
            return
        output(
            prompts,
            fmt=cfg.output_format,
            spec=OutputSpec(title="Prompts", columns=["name", "backend", "description"]),
        )
    except ArgusClientError as e:
        print_error(f"Failed to list prompts: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def get(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Prompt name.")],
    arg: Annotated[
        list[str] | None, typer.Option("--arg", "-a", help="key=value arguments.")
    ] = None,
    output_fmt: OutputOption = None,
) -> None:
    """Get and render an MCP prompt."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import (
        OutputSpec,
        apply_output_option,
        get_console,
        output,
        print_error,
        print_info,
    )

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.capabilities(type_filter="prompts", search=name)
        prompts = data.get("prompts", [])
        match = next((p for p in prompts if p.get("name") == name), None)
        if match is None:
            print_error(f"Prompt '{name}' not found.")
            raise typer.Exit(1) from None

        if cfg.output_format == "rich":
            _render_prompt_detail(get_console(), match)
        else:
            output(match, fmt=cfg.output_format, spec=OutputSpec(title=f"Prompt: {name}"))

        if arg:
            print_info(
                "Direct prompt rendering requires a running MCP session. "
                "Use 'argus shell' for interactive prompt invocation."
            )
    except ArgusClientError as e:
        print_error(f"Failed to get prompt: {e.message}")
        raise typer.Exit(1) from None


def _render_prompt_detail(console: Console, prompt: dict[str, Any]) -> None:
    """Render PromptDetail as Rich panel."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    from argus_cli.theme import COLORS

    lines = [
        f"[argus.key]Name:[/]        [argus.value]{prompt.get('name', 'N/A')}[/]",
        f"[argus.key]Backend:[/]     [argus.value]{prompt.get('backend', 'N/A')}[/]",
        f"[argus.key]Description:[/] [argus.value]{prompt.get('description', 'N/A')}[/]",
    ]
    console.print(
        Panel(
            "\n".join(lines), title=f"Prompt: {prompt.get('name', '')}", border_style=COLORS["info"]
        )
    )

    arguments = prompt.get("arguments", [])
    if arguments:
        table = Table(box=box.SIMPLE, title="Arguments")
        table.add_column("Name", style=COLORS["text"])
        table.add_column("Required", style=COLORS["text"])
        table.add_column("Description", style=COLORS["subtext"])
        for a in arguments:
            if isinstance(a, dict):
                table.add_row(
                    a.get("name", ""),
                    str(a.get("required", False)),
                    a.get("description", ""),
                )
            else:
                table.add_row(str(a), "", "")
        console.print(table)
