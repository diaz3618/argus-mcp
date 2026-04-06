"""Skills commands — list, inspect, enable, disable, apply.

Skills are managed by the Argus server via the management API.
"""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


# ── Commands ───────────────────────────────────────────────────────────


def _fetch_skills(cfg: object) -> list[dict]:
    """Fetch skills list from the server."""
    from argus_cli.client import ArgusClient

    with ArgusClient(cfg) as client:
        data = client.skills_list()
    return data.get("skills", [])


@app.command("list")
def list_skills(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Option("--search", help="Filter by name pattern.")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """List available skills."""
    from argus_cli.client import ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        skills = _fetch_skills(cfg)
    except ArgusClientError as e:
        print_error(f"Failed to list skills: {e.message}")
        raise typer.Exit(1) from None

    if search:
        q = search.lower()
        skills = [s for s in skills if q in s.get("name", "").lower()]

    if not skills:
        print_info("No skills found.")
        return

    rows = []
    for s in skills:
        rows.append(
            {
                "name": s.get("name", ""),
                "status": s.get("status", ""),
                "description": (s.get("description", "") or "")[:60],
                "version": s.get("version", ""),
            }
        )

    output(
        rows,
        fmt=cfg.output_format,
        spec=OutputSpec(
            title="Skills",
            columns=["name", "status", "description", "version"],
            key_field="status",
        ),
    )


@app.command()
def inspect(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill name to inspect.")],
    output_fmt: OutputOption = None,
) -> None:
    """Show details for a specific skill."""
    from argus_cli.client import ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        skills = _fetch_skills(cfg)
    except ArgusClientError as e:
        print_error(f"Failed to fetch skills: {e.message}")
        raise typer.Exit(1) from None

    match = next((s for s in skills if s.get("name") == name), None)
    if match is None:
        print_error(f"Skill '{name}' not found.")
        raise typer.Exit(1) from None

    if cfg.output_format == "rich":
        from rich.panel import Panel

        from argus_cli.theme import COLORS, status_markup

        console = get_console()
        lines = [
            f"[argus.key]Name:[/]        [argus.value]{match.get('name', '')}[/]",
            f"[argus.key]Version:[/]     [argus.value]{match.get('version', '')}[/]",
            f"[argus.key]Status:[/]      {status_markup(match.get('status', ''))}",
            f"[argus.key]Description:[/] [argus.value]{match.get('description', '')}[/]",
            f"[argus.key]Author:[/]      [argus.value]{match.get('author', '')}[/]",
            f"[argus.key]Tools:[/]       [argus.value]{match.get('tools', 0)}[/]",
            f"[argus.key]Workflows:[/]   [argus.value]{match.get('workflows', 0)}[/]",
        ]
        console.print(Panel("\n".join(lines), title=f"Skill: {name}", border_style=COLORS["info"]))
    else:
        output(match, fmt=cfg.output_format, spec=OutputSpec(title=f"Skill: {name}"))


@app.command()
def enable(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill name to enable.")],
) -> None:
    """Enable a skill."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_success

    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.skills_enable(name)
        if data.get("ok"):
            print_success(f"Skill '{name}' enabled.")
        else:
            print_error(f"Server did not confirm enabling skill '{name}'.")
            raise typer.Exit(1) from None
    except ArgusClientError as e:
        print_error(f"Failed to enable skill: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def disable(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill name to disable.")],
) -> None:
    """Disable a skill."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_success

    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.skills_disable(name)
        if data.get("ok"):
            print_success(f"Skill '{name}' disabled.")
        else:
            print_error(f"Server did not confirm disabling skill '{name}'.")
            raise typer.Exit(1) from None
    except ArgusClientError as e:
        print_error(f"Failed to disable skill: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def apply(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill to apply.")],
    target: Annotated[str, typer.Argument(help="Target backend or resource.")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview changes.")] = False,
) -> None:
    """Apply a skill to a target backend/resource."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_info, print_success

    cfg = ctx.obj
    if dry_run:
        try:
            skills = _fetch_skills(cfg)
        except ArgusClientError as e:
            print_error(f"Failed to fetch skills: {e.message}")
            raise typer.Exit(1) from None
        match = next((s for s in skills if s.get("name") == name), None)
        if match is None:
            print_error(f"Skill '{name}' not found.")
            raise typer.Exit(1) from None
        print_info(f"[dry-run] Would apply skill '{name}' to '{target}':")
        print_info(f"  Description: {match.get('description', 'N/A')}")
        return

    try:
        with ArgusClient(cfg) as client:
            data = client.skills_enable(name)
        if data.get("ok"):
            print_success(f"Skill '{name}' applied to '{target}'.")
        else:
            print_error(f"Failed to apply skill '{name}'.")
            raise typer.Exit(1) from None
    except ArgusClientError as e:
        print_error(f"Failed to apply skill: {e.message}")
        raise typer.Exit(1) from None
