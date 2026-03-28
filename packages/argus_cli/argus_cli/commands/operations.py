"""Operations commands — optimizer, telemetry.

Extracts operational settings from the server's StatusResponse feature_flags.
"""

from __future__ import annotations

__all__ = ["app"]

from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from argus_cli.config import CliConfig

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)


# ── Helpers ─────────────────────────────────────────────────────────────


def _get_feature_flags(cfg: CliConfig) -> dict[str, Any]:
    """Fetch status and extract feature_flags section."""
    from argus_cli.client import ArgusClient

    with ArgusClient(cfg) as client:
        data = client.status()
    flags: dict[str, Any] = data.get("feature_flags", {})
    return flags


# ── Optimizer subgroup ──────────────────────────────────────────────
optimizer_app = typer.Typer(no_args_is_help=True, help="Optimizer controls.")


@optimizer_app.command("status")
def optimizer_status(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show optimizer status."""
    from argus_cli.client import ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        flags = _get_feature_flags(cfg)
        opt = flags.get("optimizer", {})
        if not isinstance(opt, dict):
            opt = {"enabled": bool(opt)}

        info = {
            "enabled": opt.get("enabled", False),
            "keep_list": opt.get("keep_list", []),
            "strategy": opt.get("strategy", "default"),
        }

        if cfg.output_format == "rich":
            from rich.panel import Panel

            from argus_cli.theme import COLORS, status_markup

            console = get_console()
            status_str = "enabled" if info["enabled"] else "disabled"
            keep = ", ".join(info["keep_list"]) if info["keep_list"] else "none"
            lines = [
                f"[argus.key]Status:[/]   {status_markup(status_str)}",
                f"[argus.key]Strategy:[/] [argus.value]{info['strategy']}[/]",
                f"[argus.key]Keep List:[/] [argus.value]{keep}[/]",
            ]
            console.print(Panel("\n".join(lines), title="Optimizer", border_style=COLORS["info"]))
        else:
            output(info, fmt=cfg.output_format, spec=OutputSpec(title="Optimizer Status"))
    except ArgusClientError as e:
        print_error(f"Failed to get optimizer status: {e.message}")
        raise typer.Exit(1) from None


def _toggle_optimizer(cfg: CliConfig, *, enable: bool) -> None:
    """Enable or disable the optimizer via config reload."""
    from argus_cli.client import ArgusClient, ArgusClientError
    from argus_cli.output import get_console, print_error, print_success, print_warning

    action = "Enabling" if enable else "Disabling"
    past = "enabled" if enable else "disabled"
    print_warning(
        f"[stub] optimizer {past}: this command triggers a config reload but does not "
        "actually toggle the optimizer flag. Edit the server config manually to change "
        "optimizer state."
    )
    try:
        with get_console().status(f"{action} optimizer..."), ArgusClient(cfg) as client:
            result = client.reload()
        print_success(f"Optimizer {past} — server reloaded.")
        if result.get("errors"):
            for err in result["errors"]:
                print_error(f"  {err}")
    except ArgusClientError as e:
        print_error(f"Failed to {action.lower()} optimizer: {e.message}")
        raise typer.Exit(1) from None


@optimizer_app.command("enable")
def optimizer_enable(ctx: typer.Context) -> None:
    """Enable the optimizer (triggers config reload)."""
    _toggle_optimizer(ctx.obj, enable=True)


@optimizer_app.command("disable")
def optimizer_disable(ctx: typer.Context) -> None:
    """Disable the optimizer (triggers config reload)."""
    _toggle_optimizer(ctx.obj, enable=False)


app.add_typer(optimizer_app, name="optimizer")


# ── Telemetry subgroup ──────────────────────────────────────────────
telemetry_app = typer.Typer(no_args_is_help=True, help="Telemetry controls.")


@telemetry_app.command("status")
def telemetry_status(
    ctx: typer.Context,
    output_fmt: OutputOption = None,
) -> None:
    """Show telemetry configuration."""
    from argus_cli.client import ArgusClientError
    from argus_cli.output import OutputSpec, apply_output_option, get_console, output, print_error

    apply_output_option(output_fmt)
    cfg = ctx.obj
    try:
        flags = _get_feature_flags(cfg)
        tel = flags.get("telemetry", {})
        if not isinstance(tel, dict):
            tel = {"enabled": bool(tel)}

        info = {
            "enabled": tel.get("enabled", False),
            "endpoint": tel.get("endpoint", ""),
            "service_name": tel.get("service_name", "argus-mcp"),
            "protocol": tel.get("protocol", "otlp"),
        }

        if cfg.output_format == "rich":
            from rich.panel import Panel

            from argus_cli.theme import COLORS, status_markup

            console = get_console()
            status_str = "enabled" if info["enabled"] else "disabled"
            lines = [
                f"[argus.key]Status:[/]       {status_markup(status_str)}",
                f"[argus.key]Endpoint:[/]     [argus.value]{info['endpoint'] or 'not set'}[/]",
                f"[argus.key]Service Name:[/] [argus.value]{info['service_name']}[/]",
                f"[argus.key]Protocol:[/]     [argus.value]{info['protocol']}[/]",
            ]
            console.print(Panel("\n".join(lines), title="Telemetry", border_style=COLORS["info"]))
        else:
            output(info, fmt=cfg.output_format, spec=OutputSpec(title="Telemetry Status"))
    except ArgusClientError as e:
        print_error(f"Failed to get telemetry status: {e.message}")
        raise typer.Exit(1) from None


@telemetry_app.command("configure")
def telemetry_configure(
    endpoint: Annotated[str, typer.Option(help="OTLP collector endpoint URL.")] = "",
    service_name: Annotated[str, typer.Option(help="Service name for telemetry.")] = "",
) -> None:
    """Configure telemetry settings."""
    from argus_cli.output import print_info, print_success

    changes = []
    if endpoint:
        changes.append(f"endpoint={endpoint}")
    if service_name:
        changes.append(f"service_name={service_name}")

    if not changes:
        print_info("No configuration changes specified. Use --endpoint or --service-name.")
        return

    from argus_cli.output import print_warning

    print_warning(
        "[stub] telemetry configure: this command does not persist changes. "
        "Edit the server config file and run 'argus config reload' to apply."
    )
    print_success(f"Telemetry configuration noted: {', '.join(changes)}")


app.add_typer(telemetry_app, name="telemetry")
