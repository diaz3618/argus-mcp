"""Secret resolver — replaces ``secret:<name>`` references in config values.

Usage::

    from argus_mcp.secrets.resolver import resolve_secrets
    from argus_mcp.secrets.store import SecretStore

    store = SecretStore(provider_type="env")
    config = {"backend": {"token": "secret:my-api-key"}}
    resolved = resolve_secrets(config, store)
    # resolved == {"backend": {"token": "<actual value from store>"}}

Values that don't match the ``secret:`` prefix are left unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Union

from .store import SecretStore

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(r"^secret:(.+)$")


class SecretResolutionError(Exception):
    """Raised when a referenced secret cannot be found."""


def resolve_secrets(
    config: Dict[str, Any],
    store: SecretStore,
    *,
    strict: bool = False,
) -> Dict[str, Any]:
    """Walk *config* and replace ``secret:<name>`` string values.

    Parameters
    ----------
    config:
        The configuration dictionary (not mutated — a copy is returned).
    store:
        The :class:`SecretStore` to look up values from.
    strict:
        If ``True``, raise :class:`SecretResolutionError` for missing secrets.
        If ``False`` (default), log a warning and leave the reference as-is.

    Returns
    -------
    dict
        A new dictionary with resolved secret values.
    """
    return _walk(config, store, strict=strict, path="")


def _walk(
    value: Any,
    store: SecretStore,
    *,
    strict: bool,
    path: str,
) -> Any:
    if isinstance(value, dict):
        return {k: _walk(v, store, strict=strict, path=f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [
            _walk(item, store, strict=strict, path=f"{path}[{i}]") for i, item in enumerate(value)
        ]
    if isinstance(value, str):
        return _resolve_string(value, store, strict=strict, path=path)
    return value


def _resolve_string(
    value: str,
    store: SecretStore,
    *,
    strict: bool,
    path: str,
) -> str:
    match = _SECRET_PATTERN.match(value)
    if not match:
        return value

    secret_name = match.group(1)
    resolved = store.get(secret_name)

    if resolved is None:
        msg = f"Secret '{secret_name}' not found (referenced at {path})"
        if strict:
            raise SecretResolutionError(msg)
        logger.warning(msg)
        return value

    # Register the resolved value for log redaction
    try:
        from argus_mcp.display.logging_config import secret_redaction_filter

        secret_redaction_filter.register(resolved)
    except Exception as exc:
        logger.warning("Secret resolution logging failed: %s", exc)

    # nosemgrep: python-logger-credential-disclosure (logs secret name, not value)
    logger.debug("Resolved secret '%s' at %s", secret_name, path)
    return resolved


def find_secret_references(config: Dict[str, Any]) -> List[str]:
    """Return all ``secret:<name>`` references in *config*."""
    refs: List[str] = []
    _collect_refs(config, refs)
    return refs


def _collect_refs(value: Union[Dict, List, str, Any], refs: List[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _collect_refs(v, refs)
    elif isinstance(value, list):
        for item in value:
            _collect_refs(item, refs)
    elif isinstance(value, str):
        match = _SECRET_PATTERN.match(value)
        if match:
            refs.append(match.group(1))
