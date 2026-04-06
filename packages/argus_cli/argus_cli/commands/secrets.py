"""Secrets management commands — list, set, get, delete.

Secrets are stored in the server config file under ``secrets`` mapping.
Each secret has a name and a provider (env, file).
"""

from __future__ import annotations

__all__ = ["app"]

import os
import re
from pathlib import Path
from typing import Annotated

import typer

from argus_cli.output import OutputOption

app = typer.Typer(no_args_is_help=True)

_DEFAULT_SECRETS_DIR = Path("~/.config/argus-mcp/secrets").expanduser()

# Only allow simple alphanumeric/dash/underscore secret names (CWE-23 mitigation)
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_secret_name(name: str) -> None:
    """Reject secret names that could cause path traversal."""
    if not _SAFE_NAME_RE.match(name):
        from argus_cli.output import print_error

        print_error(
            f"Invalid secret name '{name}'. Use only letters, digits, hyphens, underscores."
        )
        raise typer.Exit(1) from None


def _secrets_dir() -> Path:
    """Return (and ensure exists) the secrets directory.

    Resolves the path to an absolute location to neutralize path traversal
    from the ``ARGUS_SECRETS_DIR`` environment variable (CWE-23).
    """
    raw = os.environ.get("ARGUS_SECRETS_DIR")
    if raw:
        d = Path(raw).expanduser().resolve()
        # Constrain custom dir to user home tree (CWE-23)
        if not d.is_relative_to(Path.home()):
            msg = f"ARGUS_SECRETS_DIR must be under the home directory, got: {d}"
            raise SystemExit(msg)
    else:
        d = _DEFAULT_SECRETS_DIR
    d.mkdir(parents=True, mode=0o700, exist_ok=True)
    return d


@app.command("list")
def list_secrets(
    ctx: typer.Context,
    provider: Annotated[str, typer.Option(help="Filter by provider: env, file, all.")] = "all",
    output_fmt: OutputOption = None,
) -> None:
    """List configured secret names."""
    from argus_cli.output import OutputSpec, apply_output_option, output, print_info

    apply_output_option(output_fmt)
    cfg = ctx.obj
    secrets: list[dict[str, str]] = []

    # File-based secrets
    if provider in ("all", "file"):
        sdir = _secrets_dir()
        if sdir.is_dir():
            for entry in sorted(sdir.iterdir()):
                if entry.is_file():
                    secrets.append({"name": entry.name, "provider": "file"})

    # Env-based secrets (ARGUS_SECRET_* convention)
    if provider in ("all", "env"):
        prefix = "ARGUS_SECRET_"
        for key in sorted(os.environ):
            if key.startswith(prefix):
                secrets.append(
                    {
                        "name": key[len(prefix) :].lower(),
                        "provider": "env",
                    }
                )

    if not secrets:
        print_info("No secrets found.")
        return

    spec = OutputSpec(title="Secrets", columns=["name", "provider"])
    output(secrets, fmt=cfg.output_format, spec=spec)


@app.command("set")
def set_secret(
    name: Annotated[str, typer.Argument(help="Secret name.")],
    value: Annotated[str | None, typer.Argument(help="Secret value (prompts if omitted).")] = None,
    provider: Annotated[str, typer.Option(help="Provider: file (default) or env.")] = "file",
) -> None:
    """Set a secret value."""
    from argus_cli.output import print_error, print_info, print_success

    _validate_secret_name(name)

    if value is None:
        import getpass

        value = getpass.getpass(f"Enter value for '{name}': ")

    if provider == "file":
        sdir = _secrets_dir()
        secret_path = sdir / name
        fd = os.open(str(secret_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, value.encode())
        finally:
            os.close(fd)
        print_success(f"Secret '{name}' saved to file.")
    elif provider == "env":
        env_key = f"ARGUS_SECRET_{name.upper()}"
        print_info(
            f"To set via environment, add to your shell profile:\n  export {env_key}='<value>'"
        )
    else:
        print_error(f"Unknown provider '{provider}'. Use 'file' or 'env'.")
        raise typer.Exit(1) from None


@app.command()
def get(
    name: Annotated[str, typer.Argument(help="Secret name.")],
    provider: Annotated[
        str, typer.Option(help="Provider: file or env (tries both by default).")
    ] = "all",
) -> None:
    """Get a secret value (masked by default)."""
    from argus_cli.output import print_error, print_info

    _validate_secret_name(name)

    value: str | None = None
    source: str = ""

    if provider in ("all", "file"):
        sdir = _secrets_dir()
        secret_path = sdir / name
        if secret_path.is_file():
            value = secret_path.read_text(encoding="utf-8")
            source = "file"

    if value is None and provider in ("all", "env"):
        env_key = f"ARGUS_SECRET_{name.upper()}"
        value = os.environ.get(env_key)
        if value is not None:
            source = "env"

    if value is None:
        print_error(f"Secret '{name}' not found.")
        raise typer.Exit(1) from None

    masked = value[:2] + "*" * max(len(value) - 4, 0) + value[-2:] if len(value) > 4 else "****"
    print_info(f"{name} ({source}): {masked}")


@app.command()
def delete(
    name: Annotated[str, typer.Argument(help="Secret name to delete.")],
) -> None:
    """Delete a secret."""
    from argus_cli.output import print_error, print_info, print_success

    _validate_secret_name(name)

    sdir = _secrets_dir()
    secret_path = sdir / name
    if secret_path.is_file():
        secret_path.unlink()
        print_success(f"Secret '{name}' deleted.")
        return

    env_key = f"ARGUS_SECRET_{name.upper()}"
    if env_key in os.environ:
        print_info(
            f"Secret '{name}' is set via environment variable {env_key}.\n"
            f"Remove it from your shell profile manually."
        )
    else:
        print_error(f"Secret '{name}' not found.")
        raise typer.Exit(1) from None
