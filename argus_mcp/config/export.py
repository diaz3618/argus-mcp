"""Configuration export — serialize ArgusConfig subsets to portable YAML dicts.

Supports selective filtering by entity type, tags, and active status,
with configurable secret handling (strip, mask, or preserve).
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from argus_mcp.config.schema import ArgusConfig

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(r"^secret:.+$")


class SecretHandling(str, Enum):
    """How to handle secret references during export."""

    STRIP = "strip"
    MASK = "mask"
    PRESERVE = "preserve"


class ExportFilter(BaseModel):
    """Controls which config entities are included in an export."""

    entity_types: Set[str] = Field(
        default_factory=lambda: {"backends", "registries"},
        description="Entity sections to include: backends, registries, plugins, feature_flags.",
    )
    backend_names: Optional[Set[str]] = Field(
        default=None,
        description="If set, only export these backend names.",
    )
    backend_groups: Optional[Set[str]] = Field(
        default=None,
        description="If set, only export backends in these groups.",
    )
    backend_types: Optional[Set[str]] = Field(
        default=None,
        description="If set, only export backends of these types (stdio, sse, streamable-http).",
    )


class ExportResult(BaseModel):
    """Result of an export operation."""

    export_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    exported_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    version: str = "1"
    entity_counts: Dict[str, int] = Field(default_factory=dict)
    data: Dict[str, Any] = Field(default_factory=dict)


def _mask_secrets(value: Any) -> Any:
    """Recursively mask ``secret:*`` references with ``***``."""
    if isinstance(value, dict):
        return {k: _mask_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_secrets(item) for item in value]
    if isinstance(value, str) and _SECRET_PATTERN.match(value):
        return "***"
    return value


def _strip_secrets(value: Any) -> Any:
    """Recursively remove ``secret:*`` references (replace with empty string)."""
    if isinstance(value, dict):
        return {k: _strip_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    if isinstance(value, str) and _SECRET_PATTERN.match(value):
        return ""
    return value


def _backend_matches_filter(
    name: str,
    backend_dict: Dict[str, Any],
    export_filter: ExportFilter,
) -> bool:
    """Check whether a backend passes the export filter criteria."""
    if export_filter.backend_names is not None and name not in export_filter.backend_names:
        return False
    if export_filter.backend_groups is not None:
        group = backend_dict.get("group", "default")
        if group not in export_filter.backend_groups:
            return False
    if export_filter.backend_types is not None:
        btype = backend_dict.get("type", "")
        if btype not in export_filter.backend_types:
            return False
    return True


def _serialize_backend(
    backend_cfg: Any,
) -> Dict[str, Any]:
    """Serialize a single backend config model to a plain dict."""
    if hasattr(backend_cfg, "model_dump"):
        return backend_cfg.model_dump(exclude_defaults=False)
    # Already a dict (from downstream conversion)
    if isinstance(backend_cfg, dict):
        return dict(backend_cfg)
    return {}


def export_config(
    config: ArgusConfig,
    *,
    export_filter: Optional[ExportFilter] = None,
    secret_handling: SecretHandling = SecretHandling.MASK,
) -> ExportResult:
    """Export configuration subsets as a portable dictionary.

    Parameters
    ----------
    config:
        The validated :class:`ArgusConfig` to export from.
    export_filter:
        Controls which entities are included.  Defaults to all
        backends and registries.
    secret_handling:
        How to treat ``secret:*`` references: strip, mask, or preserve.

    Returns
    -------
    ExportResult
        A result containing the exported data and metadata.
    """
    if export_filter is None:
        export_filter = ExportFilter()

    data: Dict[str, Any] = {"version": config.version}
    counts: Dict[str, int] = {}

    # ── Backends ────────────────────────────────────────────────────
    if "backends" in export_filter.entity_types:
        exported_backends: Dict[str, Any] = {}
        for name, backend in config.backends.items():
            backend_dict = _serialize_backend(backend)
            if _backend_matches_filter(name, backend_dict, export_filter):
                exported_backends[name] = backend_dict
        data["backends"] = exported_backends
        counts["backends"] = len(exported_backends)

    # ── Registries ──────────────────────────────────────────────────
    if "registries" in export_filter.entity_types:
        exported_registries: List[Dict[str, Any]] = []
        for reg in config.registries:
            if hasattr(reg, "model_dump"):
                exported_registries.append(reg.model_dump(exclude_defaults=False))
            elif isinstance(reg, dict):
                exported_registries.append(dict(reg))
        data["registries"] = exported_registries
        counts["registries"] = len(exported_registries)

    # ── Feature flags ───────────────────────────────────────────────
    if "feature_flags" in export_filter.entity_types:
        data["feature_flags"] = dict(config.feature_flags)
        counts["feature_flags"] = len(config.feature_flags)

    # ── Plugins ─────────────────────────────────────────────────────
    if "plugins" in export_filter.entity_types:
        if hasattr(config.plugins, "model_dump"):
            data["plugins"] = config.plugins.model_dump(exclude_defaults=False)
        counts["plugins"] = 1

    # ── Secret handling ─────────────────────────────────────────────
    if secret_handling == SecretHandling.MASK:
        data = _mask_secrets(data)
    elif secret_handling == SecretHandling.STRIP:
        data = _strip_secrets(data)
    # PRESERVE leaves secrets as-is

    result = ExportResult(
        entity_counts=counts,
        data=data,
    )
    logger.info(
        "Config export completed: id=%s, counts=%s",
        result.export_id,
        counts,
    )
    return result
