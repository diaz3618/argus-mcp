"""Configuration file loading and validation.

Loads a YAML configuration file, expands ``${ENV_VAR}`` placeholders,
and validates against Pydantic models defined in :mod:`schema`.

The public API is :func:`load_and_validate_config` which returns the
validated backends as ``Dict[str, Dict[str, Any]]`` for downstream code
(``ArgusService``, ``ClientManager``).
"""

import logging
import os
from typing import Any, Dict, List

import yaml
from mcp import StdioServerParameters
from pydantic import ValidationError

from argus_mcp.config.migration import expand_env_vars
from argus_mcp.config.schema import (
    ArgusConfig,
    SseBackendConfig,
    StdioBackendConfig,
    StreamableHttpBackendConfig,
)
from argus_mcp.errors import ConfigurationError

logger = logging.getLogger(__name__)

# Recognised config file extensions.
_YAML_EXTS = frozenset({".yaml", ".yml"})


def _read_config_file(cfg_fpath: str) -> Dict[str, Any]:
    """Read and parse a YAML config file from *cfg_fpath*.

    Raises :class:`ConfigurationError` on I/O or parse errors.
    """
    ext = os.path.splitext(cfg_fpath)[1].lower()
    if ext not in _YAML_EXTS:
        raise ConfigurationError(
            f"Unsupported config file extension '{ext}'. "
            "Only YAML files (.yaml, .yml) are supported."
        )

    try:
        with open(cfg_fpath, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)
    except Exception as exc:
        raise ConfigurationError(f"Error reading configuration file: {cfg_fpath}\n  {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ConfigurationError(
            "Top-level configuration content must be a YAML mapping (dictionary)."
        )
    return raw_data


# ── Post-validation conversion ──────────────────────────────────────────
# Downstream code expects Dict[str, Dict[str, Any]] with
# StdioServerParameters objects — convert Pydantic models to that format.


def _backend_to_dict(
    name: str,
    cfg: StdioBackendConfig | SseBackendConfig | StreamableHttpBackendConfig,
) -> Dict[str, Any]:
    """Convert a validated backend config model to the downstream dict format."""
    if isinstance(cfg, StdioBackendConfig):
        params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env,
        )
        entry: Dict[str, Any] = {"type": "stdio", "params": params}
        # Pass optional container overrides to client_manager
        if cfg.container is not None:
            entry["container"] = cfg.container.model_dump(exclude_none=True)
    elif isinstance(cfg, StreamableHttpBackendConfig):
        entry = {"type": "streamable-http", "url": cfg.url}
        if cfg.headers:
            entry["headers"] = cfg.headers
    else:
        # SseBackendConfig
        entry = {"type": "sse", "url": cfg.url}
        if cfg.command:
            entry["command"] = cfg.command
            entry["args"] = cfg.args
            entry["env"] = cfg.env
        if cfg.headers:
            entry["headers"] = cfg.headers

    # Inject auth configuration if present (SSE / streamable-http).
    if hasattr(cfg, "auth") and cfg.auth is not None:
        entry["auth"] = cfg.auth.model_dump()

    # Inject per-server timeout overrides (downstream code reads these).
    if cfg.timeouts.init is not None:
        entry["init_timeout"] = cfg.timeouts.init
    if cfg.timeouts.cap_fetch is not None:
        entry["cap_fetch_timeout"] = cfg.timeouts.cap_fetch
    if cfg.timeouts.sse_startup is not None:
        entry["sse_startup_delay"] = cfg.timeouts.sse_startup
    if cfg.timeouts.startup is not None:
        entry["startup_timeout"] = cfg.timeouts.startup
    if cfg.timeouts.retries is not None:
        entry["retries"] = cfg.timeouts.retries
    if cfg.timeouts.retry_delay is not None:
        entry["retry_delay"] = cfg.timeouts.retry_delay
    return entry


def _format_validation_errors(exc: ValidationError) -> str:
    """Format Pydantic validation errors into a readable multi-line string."""
    lines: List[str] = []
    for err in exc.errors():
        loc = " → ".join(str(part) for part in err["loc"])
        lines.append(f"  • {loc}: {err['msg']}")
    return "\n".join(lines)


def _maybe_resolve_secrets(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve ``secret:<name>`` references if the secrets section is enabled.

    This runs *before* Pydantic validation so that secret values are
    available as plain strings during model construction.
    """
    secrets_section = raw_data.get("secrets")
    if not isinstance(secrets_section, dict):
        return raw_data

    # Quick pre-check: is secrets resolution enabled?
    if not secrets_section.get("enabled", False):
        return raw_data

    from argus_mcp.secrets.resolver import find_secret_references, resolve_secrets
    from argus_mcp.secrets.store import SecretStore

    refs = find_secret_references(raw_data)
    if not refs:
        logger.debug("Secrets enabled but no secret: references found.")
        return raw_data

    provider_type = secrets_section.get("provider", "env")
    store_kwargs: Dict[str, str] = {}
    if provider_type == "file" and secrets_section.get("path"):
        store_kwargs["path"] = secrets_section["path"]

    store = SecretStore(provider_type=provider_type, **store_kwargs)
    strict = secrets_section.get("strict", False)

    logger.info(
        "Resolving %d secret reference(s) via '%s' provider.",
        len(refs),
        provider_type,
    )
    try:
        return resolve_secrets(raw_data, store, strict=strict)
    except Exception as exc:
        raise ConfigurationError(f"Secret resolution failed: {exc}") from exc


# ── Public API ───────────────────────────────────────────────────────────


def load_and_validate_config(cfg_fpath: str) -> Dict[str, Dict[str, Any]]:
    """Load, expand, validate, and return backend configs.

    Steps:
        1. Read YAML file
        2. Expand ``${VAR}`` environment variable references
        3. Validate against :class:`ArgusConfig` (Pydantic)
        4. Convert backend models to dict format for downstream code

    Returns:
        ``Dict[server_name, validated_config_dict]``

    Raises:
        ConfigurationError: On file I/O errors, parse errors, or
            validation failures (all errors reported at once).
    """
    logger.debug("Loading configuration file: %s", cfg_fpath)

    if not os.path.exists(cfg_fpath):
        raise ConfigurationError(f"Configuration file does not exist: {cfg_fpath}")

    # ── Read & parse (YAML) ──────────────────────────────────────────
    raw_data = _read_config_file(cfg_fpath)

    # ── Env var expansion (before validation) ────────────────────────
    raw_data = expand_env_vars(raw_data)

    # ── Secret resolution (before validation) ────────────────────────
    raw_data = _maybe_resolve_secrets(raw_data)

    # ── Pydantic validation (collects ALL errors) ────────────────────
    try:
        config = ArgusConfig.model_validate(raw_data)
    except ValidationError as exc:
        error_summary = _format_validation_errors(exc)
        raise ConfigurationError(
            f"Configuration validation failed ({len(exc.errors())} error(s)):\n" f"{error_summary}"
        ) from exc

    # ── Convert to downstream format ─────────────────────────────────
    validated: Dict[str, Dict[str, Any]] = {}
    for name, backend in config.backends.items():
        validated[name] = _backend_to_dict(name, backend)
        logger.debug("Backend '%s' (type=%s) validated.", name, backend.type)

    if not validated and config.backends:
        raise ConfigurationError("No valid server configurations were found in the file.")

    logger.info(
        "Configuration '%s' loaded (v%s). %d backend(s) validated.",
        cfg_fpath,
        config.version,
        len(validated),
    )
    return validated


def load_argus_config(cfg_fpath: str) -> ArgusConfig:
    """Load and return the full :class:`ArgusConfig` model.

    Unlike :func:`load_and_validate_config`, this returns the Pydantic
    model directly — useful when callers need server settings too.
    """
    logger.debug("Loading full config: %s", cfg_fpath)

    if not os.path.exists(cfg_fpath):
        raise ConfigurationError(f"Configuration file does not exist: {cfg_fpath}")

    raw_data = _read_config_file(cfg_fpath)

    raw_data = expand_env_vars(raw_data)

    raw_data = _maybe_resolve_secrets(raw_data)

    try:
        return ArgusConfig.model_validate(raw_data)
    except ValidationError as exc:
        error_summary = _format_validation_errors(exc)
        raise ConfigurationError(
            f"Configuration validation failed ({len(exc.errors())} error(s)):\n" f"{error_summary}"
        ) from exc
