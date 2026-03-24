"""Auth commands — status, configure, test."""

from __future__ import annotations

__all__ = ["app"]

from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


@app.command()
def status(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show current authentication status."""
    from argus_cli.output import OutputSpec, apply_output_option, output

    apply_output_option(output_fmt)
    cfg = ctx.obj
    has_token = bool(cfg.token)
    mode = "bearer" if has_token else "none"

    info = {
        "mode": mode,
        "token_configured": str(has_token).lower(),
        "server": cfg.server_url,
    }

    # Try to verify connectivity
    from argus_cli.client import ArgusClient, ArgusClientError

    try:
        with ArgusClient(cfg) as client:
            health = client.health()
        info["server_status"] = health.get("status", "unknown")
        info["server_version"] = health.get("version", "unknown")
    except ArgusClientError:
        info["server_status"] = "disconnected"

    output(info, fmt=cfg.output_format, spec=OutputSpec(title="Authentication Status"))


@app.command()
def configure(
    mode: Annotated[str, typer.Option("--mode", help="Auth mode: none, bearer.")] = "",
    token: Annotated[str, typer.Option("--token", help="Bearer token value.")] = "",
) -> None:
    """Configure authentication settings.

    .. note:: This is a stub — configuration is advisory only.
       Actual token storage is not yet implemented (TODO).
    """
    from argus_cli.output import print_error, print_info, print_success

    if not mode and not token:
        print_error("Provide --mode and/or --token.")
        raise typer.Exit(1) from None

    if mode and mode not in ("none", "bearer"):
        print_error(f"Unknown auth mode '{mode}'. Supported: none, bearer.")
        raise typer.Exit(1) from None

    lines: list[str] = []
    if mode == "none":
        lines.append("Auth mode set to 'none'. Token will not be sent.")
        print_info("Update your environment: unset ARGUS_TOKEN")
    elif mode == "bearer":
        lines.append("Auth mode set to 'bearer'.")
        if not token:
            print_info("Set token via: export ARGUS_TOKEN=<your-token> or use --token.")
    if token:
        lines.append("Token configured.")
        print_info("Set in your environment: export ARGUS_TOKEN=<token>")
        print_info("Or pass --token on each command.")

    for line in lines:
        print_success(line)


@app.command()
def test(ctx: typer.Context) -> None:
    """Test current authentication credentials."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import get_console, print_error, print_success

    config = ctx.obj
    console = get_console()
    console.print(f"[argus.key]Server:[/] {config.server_url}")
    console.print(f"[argus.key]Token:[/] {'configured' if config.token else 'not set'}")

    try:
        with ArgusClient(config) as client:
            result = client.status()
        print_success("Authentication successful — server responded OK.")
        console.print(f"  Version: {result.get('version', 'unknown')}")
    except ArgusClientError as e:
        print_error(f"Authentication test failed: {e.message}")
        raise typer.Exit(1) from None
