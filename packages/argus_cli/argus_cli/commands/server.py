"""Server lifecycle commands — start, stop, status, build, clean."""

from __future__ import annotations

__all__ = ["app"]

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from argus_cli.output import OutputOption

if TYPE_CHECKING:
    from rich.console import Console

app = typer.Typer(no_args_is_help=True)


@app.command()
def start(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 9000,
    config: Annotated[
        str | None,
        typer.Option("--config", "-c", help="Config file path.", rich_help_panel="Configuration"),
    ] = None,
    detach: Annotated[
        bool,
        typer.Option("--detach", "-d", help="Run in background.", rich_help_panel="Execution"),
    ] = False,
    name: Annotated[
        str | None,
        typer.Option(help="Instance name.", rich_help_panel="Configuration"),
    ] = None,
    verbose: Annotated[
        int,
        typer.Option("-v", count=True, help="Verbosity level.", rich_help_panel="Execution"),
    ] = 0,
) -> None:
    """Start the Argus MCP server."""
    from argus_cli.output import print_error, print_info, print_success

    # Build the argus-mcp server command
    cmd: list[str] = [sys.executable, "-m", "argus_mcp", "server"]
    if host != "127.0.0.1":
        cmd += ["--host", host]
    if port != 9000:
        cmd += ["--port", str(port)]
    if config:
        cmd += ["--config", config]
    if name:
        cmd += ["--name", name]
    for _ in range(verbose):
        cmd.append("-v")

    if detach:
        cmd.append("--detach")
        print_info(f"Starting server in background on {host}:{port}...")
    else:
        print_info(f"Starting server on {host}:{port} (foreground, Ctrl+C to stop)...")

    try:
        subprocess.run(cmd, check=True)  # noqa: S603
    except FileNotFoundError:
        print_error("argus-mcp not found. Install with: pip install argus-mcp")
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        if not detach:
            print_info("\nServer stopped.")
    except subprocess.CalledProcessError as exc:
        print_error(
            f"Server {'start failed' if detach else 'exited with'} (exit code {exc.returncode})."
        )
        raise typer.Exit(1) from None

    if detach:
        print_success(f"Server started in background on {host}:{port}")


@app.command()
def stop(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Instance name to stop.")] = None,
    timeout: Annotated[int, typer.Option(help="Shutdown timeout in seconds.")] = 30,
) -> None:
    """Stop the Argus MCP server."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import print_error, print_info, print_success

    cfg = ctx.obj
    print_info(f"Requesting shutdown (timeout={timeout}s)...")
    try:
        with ArgusClient(cfg) as client:
            result = client.shutdown(timeout_seconds=timeout)
        if result.get("shutting_down"):
            print_success("Server shutdown initiated.")
        else:
            print_error("Server did not acknowledge shutdown.")
            raise typer.Exit(1) from None
    except ArgusClientError as e:
        print_error(f"Shutdown failed: {e.message}")
        raise typer.Exit(1) from None


@app.command()
def status(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show server status and active sessions."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        with ArgusClient(cfg) as client:
            data = client.status()
    except ArgusClientError as e:
        print_error(f"Failed to get status: {e.message}")
        raise typer.Exit(1) from None

    if cfg.output_format == "rich":
        _render_status_rich(get_console(), data)
    else:
        output(data, fmt=cfg.output_format, spec=OutputSpec(title="Server Status"))


def _render_status_rich(console: Console, data: dict[str, Any]) -> None:
    """Render StatusResponse as Rich panels."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    from argus_cli.theme import COLORS, status_markup

    service = data.get("service", {})
    config_info = data.get("config", {})
    transport = data.get("transport", {})
    flags = data.get("feature_flags", {})

    # Service panel
    svc_lines = [
        f"[argus.key]Name:[/]      [argus.value]{service.get('name', 'N/A')}[/]",
        f"[argus.key]Version:[/]   [argus.value]{service.get('version', 'N/A')}[/]",
        f"[argus.key]State:[/]     {status_markup(service.get('state', 'unknown'))}",
        f"[argus.key]Uptime:[/]    [argus.value]{_fmt_uptime(service.get('uptime_seconds', 0))}[/]",
        f"[argus.key]Started:[/]   [argus.value]{service.get('started_at', 'N/A')}[/]",
    ]
    console.print(Panel("\n".join(svc_lines), title="Service", border_style=COLORS["info"]))

    # Config panel
    cfg_lines = [
        f"[argus.key]Config:[/]    [argus.value]{config_info.get('file_path', 'N/A')}[/]",
        f"[argus.key]Loaded:[/]    [argus.value]{config_info.get('loaded_at', 'N/A')}[/]",
        f"[argus.key]Backends:[/]  [argus.value]{config_info.get('backend_count', 0)}[/]",
    ]
    console.print(
        Panel("\n".join(cfg_lines), title="Configuration", border_style=COLORS["highlight"])
    )

    # Transport panel
    tr_lines = [
        f"[argus.key]Host:[/]  [argus.value]{transport.get('host', 'N/A')}[/]",
        f"[argus.key]Port:[/]  [argus.value]{transport.get('port', 'N/A')}[/]",
    ]
    if transport.get("sse_url"):
        tr_lines.append(f"[argus.key]SSE:[/]   [argus.url]{transport['sse_url']}[/]")
    if transport.get("streamable_http_url"):
        tr_lines.append(f"[argus.key]HTTP:[/]  [argus.url]{transport['streamable_http_url']}[/]")
    console.print(Panel("\n".join(tr_lines), title="Transport", border_style=COLORS["accent"]))

    # Feature flags
    if flags:
        flag_table = Table(box=box.SIMPLE, show_edge=False)
        flag_table.add_column("Flag", style=COLORS["text"])
        flag_table.add_column("Value", style=COLORS["text"])
        for k, v in flags.items():
            flag_table.add_row(k, status_markup("enabled" if v else "disabled"))
        console.print(Panel(flag_table, title="Feature Flags", border_style=COLORS["overlay"]))


def _fmt_uptime(seconds: float) -> str:
    """Format seconds into a human-readable uptime string."""
    s = int(seconds)
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes, s = divmod(s, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{s}s")
    return " ".join(parts)


@app.command()
def build(
    config: Annotated[str | None, typer.Option("--config", "-c", help="Config file.")] = None,
) -> None:
    """Pre-build containers for stdio backends."""
    from argus_cli.output import print_error, print_info, print_success

    cmd = [sys.executable, "-m", "argus_mcp", "build"]
    if config:
        cmd += ["--config", config]

    print_info("Building container images for stdio backends...")
    try:
        subprocess.run(cmd, check=True)  # noqa: S603
        print_success("Build complete.")
    except FileNotFoundError:
        print_error("argus-mcp not found. Install with: pip install argus-mcp")
        raise typer.Exit(1) from None
    except subprocess.CalledProcessError as exc:
        print_error(f"Build failed (exit code {exc.returncode}).")
        raise typer.Exit(1) from None


@app.command()
def clean(
    images: Annotated[bool, typer.Option(help="Remove built container images.")] = False,
    network: Annotated[bool, typer.Option(help="Remove Docker networks.")] = False,
    all_resources: Annotated[bool, typer.Option("--all", help="Remove everything.")] = False,
) -> None:
    """Clean server resources (images, networks, state)."""
    from argus_cli.output import print_info, print_success, print_warning

    if not (images or network or all_resources):
        print_warning("Specify --images, --network, or --all.")
        raise typer.Exit(1) from None

    if all_resources:
        images = network = True

    # Clean argus state directory
    state_dir = Path.home() / ".argus"
    if all_resources and state_dir.is_dir():
        sessions_dir = state_dir / "sessions"
        if sessions_dir.is_dir():
            shutil.rmtree(sessions_dir)
            print_info("Cleaned session state.")

    if images:
        print_info("Removing container images created by argus-mcp...")
        _run_optional(["docker", "image", "prune", "-f", "--filter", "label=built-by=argus-mcp"])
        print_success("Images cleaned.")

    if network:
        print_info("Removing Docker networks created by argus-mcp...")
        _run_optional(["docker", "network", "prune", "-f", "--filter", "label=built-by=argus-mcp"])
        print_success("Networks cleaned.")


def _run_optional(cmd: list[str]) -> None:
    """Run a command, silently ignoring if the binary is not found."""
    if not shutil.which(cmd[0]):
        return
    import contextlib

    with contextlib.suppress(OSError):
        subprocess.run(cmd, check=False, capture_output=True)  # noqa: S603
