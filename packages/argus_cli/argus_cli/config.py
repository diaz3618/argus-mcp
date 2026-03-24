"""CLI configuration — YAML file, .env file, env vars, and flag resolution."""

from __future__ import annotations

__all__ = [
    "CONFIG_DIR",
    "CONFIG_FILE",
    "DEFAULT_SERVER_URL",
    "MANAGE_API_PREFIX",
    "CliConfig",
    "get_config",
    "get_config_source",
    "is_repl_mode",
    "set_config",
    "set_repl_mode",
]

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

DEFAULT_SERVER_URL = "http://127.0.0.1:9000"
MANAGE_API_PREFIX = "/manage/v1"
CONFIG_DIR = Path.home() / ".config" / "argus-mcp"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# ── YAML config loader ─────────────────────────────────────────────────


_config_source: Path | None = None


def _load_yaml_config() -> dict[str, Any]:
    """Load config from CWD/config.yaml → ~/.config/argus-mcp/config.yaml."""
    global _config_source
    candidates = [Path.cwd() / "config.yaml", CONFIG_FILE]
    for path in candidates:
        if path.is_file():
            try:
                import yaml

                text = path.read_text(encoding="utf-8")
                data = yaml.safe_load(text)
                if isinstance(data, dict):
                    _config_source = path
                    return data
            except (FileNotFoundError, yaml.YAMLError):
                continue
    return {}


def _save_yaml_config(data: dict[str, Any]) -> None:
    """Write config dict to ~/.config/argus-mcp/config.yaml."""
    import yaml

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _validate_server_url(url: str) -> None:
    """Validate that the server URL uses http or https scheme."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        msg = f"Invalid server URL scheme '{parsed.scheme}'. Only http and https are supported."
        raise ValueError(msg)


@dataclass
class CliConfig:
    """Resolved CLI configuration from flags, env vars, YAML file, and defaults.

    Attributes:
        server_url: Argus server base URL (e.g. ``http://127.0.0.1:9000``).
        token: Optional management API bearer token.
        output_format: Default output format (``rich``, ``json``, ``text``, ``table``).
        no_color: Disable coloured output when ``True``.
        theme: Active Rich theme name.
        show_toolbar: Show the REPL status toolbar.
        vi_mode: Enable vi key bindings in the REPL.
        poll_interval: Seconds between background status polls.
        history_limit: Maximum REPL history entries to persist.
    """

    server_url: str = field(default_factory=lambda: DEFAULT_SERVER_URL)
    token: str | None = None
    output_format: str = "rich"
    no_color: bool = False
    theme: str = "catppuccin-mocha"

    # REPL settings
    show_toolbar: bool = True
    vi_mode: bool = False
    poll_interval: int = 30
    history_limit: int = 50

    @property
    def base_url(self) -> str:
        """Management API base URL."""
        return f"{self.server_url.rstrip('/')}{MANAGE_API_PREFIX}"

    @classmethod
    def resolve(
        cls,
        server: str | None = None,
        token: str | None = None,
        output: str | None = None,
        no_color: bool = False,
        theme: str | None = None,
    ) -> CliConfig:
        """Resolve config: CLI flags → env vars → YAML file → defaults."""
        load_dotenv(override=False)
        yaml_cfg = _load_yaml_config()

        resolved_server = (
            server
            or os.environ.get("ARGUS_SERVER_URL")
            or yaml_cfg.get("server_url")
            or DEFAULT_SERVER_URL
        )
        resolved_token = token or os.environ.get("ARGUS_MGMT_TOKEN") or yaml_cfg.get("token")
        resolved_output = (
            output
            or os.environ.get("ARGUS_OUTPUT_FORMAT")
            or yaml_cfg.get("output_format")
            or "rich"
        )
        resolved_theme = theme or yaml_cfg.get("theme", "catppuccin-mocha")

        # Auto-detect: if stdout is a pipe and no explicit format was given,
        # default to json for machine-friendly piping.
        explicit_output = (
            output or os.environ.get("ARGUS_OUTPUT_FORMAT") or yaml_cfg.get("output_format")
        )
        if not explicit_output and resolved_output == "rich" and not _is_terminal():
            resolved_output = "json"

        resolved_no_color = no_color or os.environ.get("NO_COLOR", "") != ""

        # REPL settings (config file only, no flags/env)
        show_toolbar = yaml_cfg.get("show_toolbar", True)
        vi_mode = yaml_cfg.get("vi_mode", False)
        poll_interval = yaml_cfg.get("poll_interval", 30)
        history_limit = yaml_cfg.get("history_limit", 50)

        # Validate server URL scheme (SSRF prevention)
        _validate_server_url(resolved_server)

        return cls(
            server_url=resolved_server,
            token=resolved_token,
            output_format=resolved_output,
            no_color=resolved_no_color,
            theme=resolved_theme,
            show_toolbar=bool(show_toolbar),
            vi_mode=bool(vi_mode),
            poll_interval=int(poll_interval),
            history_limit=int(history_limit),
        )


def _is_terminal() -> bool:
    """Check if stdout is a terminal (not a pipe)."""
    import sys

    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# ── Global config state ───────────────────────────────────────────────

_active_config: CliConfig | None = None
_in_repl: bool = False


def get_config() -> CliConfig:
    """Return the resolved CLI config."""
    if _active_config is None:
        return CliConfig.resolve()
    return _active_config


def set_config(config: CliConfig) -> None:
    """Set the active CLI config (called by main callback)."""
    global _active_config
    _active_config = config


def set_repl_mode(enabled: bool) -> None:
    """Toggle REPL mode flag (skip re-resolution in main callback)."""
    global _in_repl
    _in_repl = enabled


def is_repl_mode() -> bool:
    """Check if currently running inside the REPL."""
    return _in_repl


def get_config_source() -> Path | None:
    """Return the path of the loaded config file, or None."""
    return _config_source
