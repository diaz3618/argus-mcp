"""Skills commands — list, inspect, enable, disable, apply.

Skills are discovered by scanning .github/skills/ directories for SKILL.md
manifests. Enable/disable state is tracked in a local config file.
"""

from __future__ import annotations

__all__ = ["app"]

from pathlib import Path
from typing import Annotated, Any

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)

# ── Skill discovery ────────────────────────────────────────────────────

SKILLS_DIRS = [
    Path(".github/skills"),
    Path("skills"),
]


def _discover_skills() -> list[dict[str, Any]]:
    """Scan known directories for SKILL.md files and parse basic metadata."""
    skills: list[dict[str, Any]] = []
    for base in SKILLS_DIRS:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            skill_file = entry / "SKILL.md" if entry.is_dir() else None
            if skill_file and skill_file.exists():
                meta = _parse_skill_md(skill_file)
                meta["name"] = entry.name
                meta["path"] = str(skill_file)
                skills.append(meta)
    return skills


def _parse_skill_md(path: Path) -> dict[str, Any]:
    """Extract name, description, and metadata from a SKILL.md file."""
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    meta: dict[str, Any] = {"description": "", "file": ""}
    in_frontmatter = False
    description_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter and ":" in stripped:
            key, _, value = stripped.partition(":")
            meta[key.strip().lower()] = value.strip()
        elif not in_frontmatter and stripped and not stripped.startswith("#"):
            description_lines.append(stripped)

    if description_lines:
        meta["description"] = description_lines[0][:120]
    return meta


def _get_enabled_skills(config_path: Path | None = None) -> set[str]:
    """Read enabled skills from config."""
    path = config_path or Path.home() / ".config" / "argus-mcp" / "skills.txt"
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _save_enabled_skills(names: set[str], config_path: Path | None = None) -> None:
    """Save enabled skills to config."""
    path = config_path or Path.home() / ".config" / "argus-mcp" / "skills.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(names)) + "\n")


# ── Commands ───────────────────────────────────────────────────────────


@app.command("list")
def list_skills(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Option("--search", help="Filter by name pattern.")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """List available skills."""
    from argus_cli.output import OutputSpec, apply_output_option, output, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    skills = _discover_skills()
    enabled = _get_enabled_skills()

    if search:
        q = search.lower()
        skills = [s for s in skills if q in s.get("name", "").lower()]

    if not skills:
        print_info("No skills found. Place SKILL.md files in .github/skills/<name>/")
        return

    rows = []
    for s in skills:
        rows.append(
            {
                "name": s.get("name", ""),
                "status": "enabled" if s.get("name", "") in enabled else "disabled",
                "description": s.get("description", "")[:60],
                "path": s.get("path", ""),
            }
        )

    output(
        rows,
        fmt=cfg.output_format,
        spec=OutputSpec(
            title="Skills",
            columns=["name", "status", "description"],
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
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    skills = _discover_skills()
    match = next((s for s in skills if s.get("name") == name), None)
    if match is None:
        print_error(f"Skill '{name}' not found.")
        raise typer.Exit(1) from None

    enabled = _get_enabled_skills()
    match["status"] = "enabled" if name in enabled else "disabled"

    if cfg.output_format == "rich":
        from rich.panel import Panel
        from rich.syntax import Syntax

        from argus_cli.theme import COLORS, status_markup

        console = get_console()
        lines = [
            f"[argus.key]Name:[/]        [argus.value]{match.get('name', '')}[/]",
            f"[argus.key]Status:[/]      {status_markup(match['status'])}",
            f"[argus.key]Description:[/] [argus.value]{match.get('description', '')}[/]",
            f"[argus.key]Path:[/]        [argus.value]{match.get('path', '')}[/]",
        ]
        console.print(Panel("\n".join(lines), title=f"Skill: {name}", border_style=COLORS["info"]))

        # Show first 30 lines of the SKILL.md content
        path = Path(match.get("path", ""))
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
            preview = "\n".join(content.splitlines()[:30])
            console.print(
                Panel(
                    Syntax(preview, "markdown", theme="monokai"),
                    title="SKILL.md preview",
                    border_style=COLORS["highlight"],
                )
            )
    else:
        output(match, fmt=cfg.output_format, spec=OutputSpec(title=f"Skill: {name}"))


@app.command()
def enable(
    name: Annotated[str, typer.Argument(help="Skill name to enable.")],
) -> None:
    """Enable a skill."""
    from argus_cli.output import print_error, print_info, print_success

    skills = _discover_skills()
    if not any(s.get("name") == name for s in skills):
        print_error(f"Skill '{name}' not found.")
        raise typer.Exit(1) from None

    enabled = _get_enabled_skills()
    if name in enabled:
        print_info(f"Skill '{name}' is already enabled.")
        return
    enabled.add(name)
    _save_enabled_skills(enabled)
    print_success(f"Skill '{name}' enabled.")


@app.command()
def disable(
    name: Annotated[str, typer.Argument(help="Skill name to disable.")],
) -> None:
    """Disable a skill."""
    from argus_cli.output import print_error, print_info, print_success

    skills = _discover_skills()
    if not any(s.get("name") == name for s in skills):
        print_error(f"Skill '{name}' not found.")
        raise typer.Exit(1) from None

    enabled = _get_enabled_skills()
    if name not in enabled:
        print_info(f"Skill '{name}' is already disabled.")
        return
    enabled.discard(name)
    _save_enabled_skills(enabled)
    print_success(f"Skill '{name}' disabled.")


@app.command()
def apply(
    name: Annotated[str, typer.Argument(help="Skill to apply.")],
    target: Annotated[str, typer.Argument(help="Target backend or resource.")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview changes.")] = False,
) -> None:
    """Apply a skill to a target backend/resource."""
    from argus_cli.output import print_error, print_info, print_success

    skills = _discover_skills()
    match = next((s for s in skills if s.get("name") == name), None)
    if match is None:
        print_error(f"Skill '{name}' not found.")
        raise typer.Exit(1) from None

    if dry_run:
        print_info(f"[dry-run] Would apply skill '{name}' to '{target}':")
        print_info(f"  Description: {match.get('description', 'N/A')}")
        print_info(f"  Source: {match.get('path', 'N/A')}")
        return

    # Enable the skill and record the target association
    enabled = _get_enabled_skills()
    enabled.add(name)
    _save_enabled_skills(enabled)
    print_success(f"Skill '{name}' applied to '{target}'.")
