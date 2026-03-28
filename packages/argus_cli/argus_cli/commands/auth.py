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

    Persists auth mode and token to ~/.config/argus-mcp/config.yaml.
    """
    from argus_cli.config import CONFIG_FILE, _load_yaml_config, _save_yaml_config
    from argus_cli.output import print_error, print_success

    if not mode and not token:
        print_error("Provide --mode and/or --token.")
        raise typer.Exit(1) from None

    if mode and mode not in ("none", "bearer"):
        print_error(f"Unknown auth mode '{mode}'. Supported: none, bearer.")
        raise typer.Exit(1) from None

    data = _load_yaml_config()
    auth = data.get("auth") if isinstance(data.get("auth"), dict) else {}

    if mode:
        auth["mode"] = mode
    if token:
        auth["token"] = token
    if mode == "none":
        auth.pop("token", None)

    data["auth"] = auth
    _save_yaml_config(data)

    # Restrict file permissions when a token is stored
    if auth.get("token"):
        CONFIG_FILE.chmod(0o600)

    if mode:
        print_success(f"Auth mode set to '{mode}'.")
    if token:
        print_success("Token saved to config.")
    if mode == "none":
        print_success("Token cleared from config.")


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
