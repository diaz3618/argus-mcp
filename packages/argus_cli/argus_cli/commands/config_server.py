"""Server-side config operations — show, validate, diff, reload, export.

These commands interact with the Argus server or validate config files
on disk.  They are mounted into the main ``config`` command group by
``config_cmd.py``.
"""

from __future__ import annotations

__all__ = ["app"]

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


@app.command()
def show(
    ctx: typer.Context,
    section: Annotated[str | None, typer.Option(help="Show specific config section.")] = None,
    output_fmt: OutputOption = None,
) -> None:
    """Show the running server configuration."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, output, print_error, render_yaml

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.status()
        config_data = data.get("config", data)
        if section and isinstance(config_data, dict):
            config_data = config_data.get(section, {})
            if not config_data:
                print_error(f"Section '{section}' not found.")
                raise typer.Exit(1) from None

        if cfg.output_format == "rich":
            import yaml

            yaml_str = yaml.dump(config_data, default_flow_style=False, sort_keys=False)
            render_yaml(yaml_str, title=f"Configuration{f' ({section})' if section else ''}")
        else:
            spec = OutputSpec(title="Server Configuration")
            output(config_data, fmt=cfg.output_format, spec=spec)
    except ArgusClientError as e:
        print_error(f"Failed to get config: {e.message}")
        raise typer.Exit(1) from None
    except ImportError:
        spec = OutputSpec(title="Server Configuration")
        output(config_data, fmt=cfg.output_format, spec=spec)


def _resolve_config_path(path: str | None) -> Path:
    """Resolve config file path from argument or default candidates."""
    from argus_cli.output import print_error

    if path is None:
        candidates = [
            Path("argus-mcp.yaml"),
            Path("argus-mcp.yml"),
            Path("~/.config/argus-mcp/config.yaml").expanduser(),
        ]
        resolved = next((c for c in candidates if c.is_file()), None)
        if resolved is None:
            print_error("No config file specified and no default found.")
            raise typer.Exit(1) from None
        return resolved

    config_path = Path(path)
    if not config_path.is_file():
        print_error(f"File not found: {config_path}")
        raise typer.Exit(1) from None
    return config_path


def _load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load and parse a YAML config file, exiting on errors."""
    from argus_cli.output import print_error

    try:
        import yaml

        config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except ImportError:
        print_error("PyYAML is required for config validation. Install with: pip install pyyaml")
        raise typer.Exit(1) from None
    except yaml.YAMLError as e:
        print_error(f"YAML parse error: {e}")
        raise typer.Exit(1) from None

    if not isinstance(config_data, dict):
        print_error("Config file must be a YAML mapping.")
        raise typer.Exit(1) from None
    return config_data


def _validate_backends(backends: Any, errors: list[str], warnings: list[str]) -> None:
    """Validate the backends list entries."""
    if isinstance(backends, list):
        for i, b in enumerate(backends):
            if not isinstance(b, dict):
                errors.append(f"backends[{i}]: must be a mapping")
                continue
            if "name" not in b:
                errors.append(f"backends[{i}]: missing required 'name'")
            if "type" not in b:
                errors.append(f"backends[{i}]: missing required 'type'")
            btype = b.get("type", "")
            if btype not in ("stdio", "sse", "streamable_http", ""):
                warnings.append(f"backends[{i}] ({b.get('name', '?')}): unknown type '{btype}'")
    elif backends is not None:
        errors.append("'backends' must be a list")


@app.command()
def validate(
    path: Annotated[str | None, typer.Argument(help="Config file to validate.")] = None,
) -> None:
    """Validate a configuration file (offline, no server needed)."""
    from argus_cli.output import print_error, print_info, print_success, print_warning

    config_path = _resolve_config_path(path)
    print_info(f"Validating {config_path}...")

    config_data = _load_yaml_config(config_path)

    errors: list[str] = []
    warnings: list[str] = []

    if "backends" not in config_data:
        errors.append("Missing required key: 'backends'")

    _validate_backends(config_data.get("backends", []), errors, warnings)

    # Server port validation
    server = config_data.get("server", {})
    if isinstance(server, dict):
        port = server.get("port")
        if port is not None and (not isinstance(port, int) or port < 1 or port > 65535):
            errors.append(f"server.port: invalid port number '{port}'")

    if errors:
        for err in errors:
            print_error(f"  {err}")
        print_error(f"Validation failed: {len(errors)} error(s), {len(warnings)} warning(s).")
        raise typer.Exit(1) from None

    for w in warnings:
        print_warning(f"  {w}")
    print_success(f"Configuration valid ({len(warnings)} warning(s)).")


@app.command()
def diff(ctx: typer.Context) -> None:
    """Show diff between running config and disk config."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import get_console, print_error, print_info

    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            running = client.status()
    except ArgusClientError as e:
        print_error(f"Failed to get running config: {e.message}")
        raise typer.Exit(1) from None

    running_config = running.get("config", {})
    raw_path = running_config.get("file_path")
    if not raw_path:
        print_error("No config file path reported by server.")
        raise typer.Exit(1) from None

    from pathlib import Path

    # Resolve and constrain to prevent path traversal from server response (CWE-23)
    file_path = Path(raw_path).resolve()
    allowed_dirs = [
        Path("~/.config/argus-mcp").expanduser().resolve(),
        Path.cwd().resolve(),
    ]
    if not any(file_path.is_relative_to(d) for d in allowed_dirs):
        print_error(f"Config path '{file_path}' is outside allowed directories.")
        raise typer.Exit(1) from None

    if not file_path.is_file():
        print_error(f"Config file not found at: {file_path}")
        raise typer.Exit(1) from None

    try:
        import yaml

        disk_config = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except ImportError:
        print_error("PyYAML required. Install with: pip install pyyaml")
        raise typer.Exit(1) from None
    except yaml.YAMLError as e:
        print_error(f"Failed to parse disk config: {e}")
        raise typer.Exit(1) from None

    # Compare as JSON strings for readable diff
    running_str = json.dumps(running_config, indent=2, sort_keys=True, default=str)
    disk_str = json.dumps(disk_config, indent=2, sort_keys=True, default=str)

    if running_str == disk_str:
        print_info("Running config matches disk config.")
        return

    import difflib

    diff_lines = list(
        difflib.unified_diff(
            running_str.splitlines(keepends=True),
            disk_str.splitlines(keepends=True),
            fromfile="running",
            tofile="disk",
        )
    )

    console = get_console()
    from rich.syntax import Syntax

    console.print(Syntax("".join(diff_lines), "diff", theme="monokai"))


@app.command()
def reload(ctx: typer.Context) -> None:
    """Reload server configuration from disk."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_info, print_success

    cfg = ctx.obj
    try:
        from argus_cli.output import get_console

        with get_console().status("Reloading configuration..."), ArgusClient(cfg) as client:
            result = client.reload()
        if result.get("reloaded"):
            added = result.get("backends_added", [])
            removed = result.get("backends_removed", [])
            changed = result.get("backends_changed", [])
            errors = result.get("errors", [])
            print_success("Configuration reloaded.")
            if added:
                print_info(f"  Added: {', '.join(added)}")
            if removed:
                print_info(f"  Removed: {', '.join(removed)}")
            if changed:
                print_info(f"  Changed: {', '.join(changed)}")
            if errors:
                for e in errors:
                    print_error(f"  {e}")
        else:
            print_error("Reload did not succeed.")
            raise typer.Exit(1) from None
    except ArgusClientError as e:
        print_error(f"Reload failed: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def export(
    ctx: typer.Context,
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Export format: yaml or json.")
    ] = "yaml",
) -> None:
    """Export the running configuration."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error

    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.status()
        config_data = data.get("config", data)

        if fmt == "json":
            print(json.dumps(config_data, indent=2, default=str))
        else:
            import yaml

            print(yaml.dump(config_data, default_flow_style=False, sort_keys=False))
    except ArgusClientError as e:
        print_error(f"Failed to export config: {e.message}")
        raise typer.Exit(1) from None
    except ImportError:
        print(json.dumps(config_data, indent=2, default=str))
