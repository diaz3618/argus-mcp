"""YAML/JSON catalog service for batch MCP server onboarding.

Provides a structured workflow:
    1. **Parse** — Load catalog from YAML/JSON string or file path
    2. **Validate** — Validate each entry against Argus backend schemas
    3. **Stage** — Build a staged preview of what would be applied
    4. **Commit** — Apply staged entries to an ArgusConfig with per-item results

Optional health-check step can be inserted between stage and commit.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import yaml
from pydantic import BaseModel, Field, ValidationError

from argus_mcp.config.schema import ArgusConfig, BackendConfig
from argus_mcp.config.schema_backends import (
    SseBackendConfig,
    StdioBackendConfig,
    StreamableHttpBackendConfig,
)

logger = logging.getLogger(__name__)

MAX_CATALOG_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
MAX_CATALOG_ENTRIES: int = 500


class CatalogEntryStatus(str, Enum):
    """Status of a single catalog entry after processing."""

    STAGED = "staged"
    ADDED = "added"
    SKIPPED = "skipped"
    FAILED = "failed"
    HEALTH_OK = "health_ok"
    HEALTH_FAILED = "health_failed"


class CatalogEntry(BaseModel):
    """A single server definition from a YAML/JSON catalog file."""

    name: str
    description: str = ""
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    headers: Optional[Dict[str, str]] = None
    groups: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    filters: Optional[Dict[str, Any]] = None
    timeout: Optional[Dict[str, Any]] = None


class CatalogItemResult(BaseModel):
    """Result for a single catalog entry after processing."""

    name: str
    status: CatalogEntryStatus
    backend_type: str = ""
    error: Optional[str] = None


class CatalogResult(BaseModel):
    """Aggregate result from a catalog operation (stage or commit)."""

    catalog_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    processed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dry_run: bool = False
    total_entries: int = 0
    items: List[CatalogItemResult] = Field(default_factory=list)

    @property
    def added_count(self) -> int:
        return sum(1 for i in self.items if i.status == CatalogEntryStatus.ADDED)

    @property
    def staged_count(self) -> int:
        return sum(1 for i in self.items if i.status == CatalogEntryStatus.STAGED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for i in self.items if i.status == CatalogEntryStatus.SKIPPED)

    @property
    def failed_count(self) -> int:
        return sum(1 for i in self.items if i.status == CatalogEntryStatus.FAILED)

    @property
    def success(self) -> bool:
        return self.failed_count == 0

    def summary(self) -> str:
        parts = [f"catalog={self.catalog_id}"]
        if self.dry_run:
            parts.append("dry_run=True")
        parts.append(f"total={self.total_entries}")
        if self.staged_count:
            parts.append(f"staged={self.staged_count}")
        if self.added_count:
            parts.append(f"added={self.added_count}")
        if self.skipped_count:
            parts.append(f"skipped={self.skipped_count}")
        if self.failed_count:
            parts.append(f"failed={self.failed_count}")
        return ", ".join(parts)


class CatalogParseError(Exception):
    """Raised when the catalog payload cannot be parsed."""


def parse_catalog(
    raw: str,
    *,
    max_size_bytes: int = MAX_CATALOG_SIZE_BYTES,
) -> List[CatalogEntry]:
    """Parse a YAML or JSON catalog string into CatalogEntry objects.

    The catalog format supports:
        - A top-level ``servers`` key containing a dict of name → config
        - A top-level list of entries (each must have a ``name`` key)
        - A top-level dict of name → config (without ``servers`` wrapper)

    Raises CatalogParseError on invalid payloads.
    """
    if len(raw.encode("utf-8", errors="replace")) > max_size_bytes:
        msg = f"Catalog exceeds maximum size ({max_size_bytes} bytes)"
        raise CatalogParseError(msg)

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML/JSON: {exc}"
        raise CatalogParseError(msg) from exc

    if data is None:
        return []

    entries: List[CatalogEntry] = []

    if isinstance(data, dict):
        # Check for `servers` wrapper key
        servers_data = data.get("servers", data)
        if isinstance(servers_data, dict):
            for name, cfg in servers_data.items():
                if not isinstance(cfg, dict):
                    continue
                cfg.setdefault("name", name)
                entries.append(_parse_entry(name, cfg))
        elif isinstance(servers_data, list):
            for item in servers_data:
                if isinstance(item, dict) and "name" in item:
                    entries.append(_parse_entry(item["name"], item))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "name" in item:
                entries.append(_parse_entry(item["name"], item))
    else:
        msg = "Catalog must be a YAML mapping or list"
        raise CatalogParseError(msg)

    return entries


def parse_catalog_file(
    path: str | Path,
    *,
    max_size_bytes: int = MAX_CATALOG_SIZE_BYTES,
) -> List[CatalogEntry]:
    """Read and parse a catalog from a file path."""
    p = Path(path)
    if not p.is_file():
        msg = f"Catalog file not found: {p}"
        raise CatalogParseError(msg)

    raw = p.read_text(encoding="utf-8")
    return parse_catalog(raw, max_size_bytes=max_size_bytes)


def _parse_entry(name: str, raw: Dict[str, Any]) -> CatalogEntry:
    """Validate a single catalog entry dict into a CatalogEntry model."""
    try:
        return CatalogEntry(name=name, **{k: v for k, v in raw.items() if k != "name"})
    except ValidationError as exc:
        msg = f"Invalid catalog entry '{name}': {exc}"
        raise CatalogParseError(msg) from exc


def _entry_to_backend(
    entry: CatalogEntry,
    *,
    catalog_id: str,
    created_via: str = "catalog",
) -> BackendConfig:
    """Convert a CatalogEntry to an Argus BackendConfig.

    Raises ValueError if the entry has an unsupported transport.
    """
    provenance = {
        "created_via": created_via,
        "import_batch_id": catalog_id,
        "metadata_version": 1,
    }

    transport = entry.transport.lower()

    if transport == "stdio":
        if not entry.command:
            msg = f"stdio entry '{entry.name}' requires a 'command'"
            raise ValueError(msg)
        kwargs: Dict[str, Any] = {
            "type": "stdio",
            "command": entry.command,
            **provenance,
        }
        if entry.args:
            kwargs["args"] = entry.args
        if entry.env:
            kwargs["env"] = entry.env
        if entry.groups:
            kwargs["groups"] = entry.groups
        if entry.filters:
            kwargs["filters"] = entry.filters
        if entry.timeout:
            kwargs["timeout"] = entry.timeout
        return StdioBackendConfig(**kwargs)

    if transport in ("sse", "streamable-http"):
        if not entry.url:
            msg = f"{transport} entry '{entry.name}' requires a 'url'"
            raise ValueError(msg)
        kwargs = {
            "type": transport,
            "url": entry.url,
            **provenance,
        }
        if entry.headers:
            kwargs["headers"] = entry.headers
        if entry.groups:
            kwargs["groups"] = entry.groups
        if entry.filters:
            kwargs["filters"] = entry.filters
        if entry.timeout:
            kwargs["timeout"] = entry.timeout
        if transport == "sse":
            return SseBackendConfig(**kwargs)
        return StreamableHttpBackendConfig(**kwargs)

    msg = f"Unsupported transport '{transport}' for entry '{entry.name}'"
    raise ValueError(msg)


# Type alias for optional async health-check callback.
# Signature: (name, backend_config) → True if healthy
HealthCheckFn = Callable[[str, BackendConfig], bool]


def stage_catalog(
    entries: List[CatalogEntry],
    config: ArgusConfig,
    *,
    skip_existing: bool = True,
    max_entries: int = MAX_CATALOG_ENTRIES,
    catalog_id: Optional[str] = None,
) -> CatalogResult:
    """Build a staged preview of catalog application.

    Returns a CatalogResult with each entry marked STAGED or SKIPPED/FAILED.
    No mutations are applied to *config*.
    """
    cid = catalog_id or uuid.uuid4().hex[:12]
    result = CatalogResult(
        catalog_id=cid,
        dry_run=True,
        total_entries=len(entries),
    )

    if len(entries) > max_entries:
        for entry in entries:
            result.items.append(
                CatalogItemResult(
                    name=entry.name,
                    status=CatalogEntryStatus.FAILED,
                    backend_type=entry.transport,
                    error=f"Batch exceeds maximum entries ({max_entries})",
                )
            )
        return result

    existing_names: Set[str] = set(config.backends.keys()) if config.backends else set()

    for entry in entries:
        if skip_existing and entry.name in existing_names:
            result.items.append(
                CatalogItemResult(
                    name=entry.name,
                    status=CatalogEntryStatus.SKIPPED,
                    backend_type=entry.transport,
                    error="Already exists in config",
                )
            )
            continue

        try:
            _entry_to_backend(entry, catalog_id=cid)
            result.items.append(
                CatalogItemResult(
                    name=entry.name,
                    status=CatalogEntryStatus.STAGED,
                    backend_type=entry.transport,
                )
            )
        except (ValueError, ValidationError) as exc:
            result.items.append(
                CatalogItemResult(
                    name=entry.name,
                    status=CatalogEntryStatus.FAILED,
                    backend_type=entry.transport,
                    error=str(exc),
                )
            )

    return result


def commit_catalog(
    entries: List[CatalogEntry],
    config: ArgusConfig,
    *,
    skip_existing: bool = True,
    max_entries: int = MAX_CATALOG_ENTRIES,
    health_check: Optional[HealthCheckFn] = None,
    catalog_id: Optional[str] = None,
) -> CatalogResult:
    """Apply catalog entries to *config* with per-item results.

    Parameters
    ----------
    entries:
        Parsed catalog entries to onboard.
    config:
        The live ArgusConfig to mutate (add backends to).
    skip_existing:
        When True, silently skip entries whose name already exists.
    max_entries:
        Maximum number of entries in one batch.
    health_check:
        Optional callable ``(name, backend_config) → bool``.
        Called after conversion; if it returns False the entry is marked
        HEALTH_FAILED and not added.
    catalog_id:
        Override the auto-generated catalog batch ID.

    Returns
    -------
    CatalogResult with per-item statuses.
    """
    cid = catalog_id or uuid.uuid4().hex[:12]
    result = CatalogResult(
        catalog_id=cid,
        dry_run=False,
        total_entries=len(entries),
    )

    if len(entries) > max_entries:
        for entry in entries:
            result.items.append(
                CatalogItemResult(
                    name=entry.name,
                    status=CatalogEntryStatus.FAILED,
                    backend_type=entry.transport,
                    error=f"Batch exceeds maximum entries ({max_entries})",
                )
            )
        return result

    if config.backends is None:
        config.backends = {}

    existing_names: Set[str] = set(config.backends.keys())

    for entry in entries:
        if skip_existing and entry.name in existing_names:
            result.items.append(
                CatalogItemResult(
                    name=entry.name,
                    status=CatalogEntryStatus.SKIPPED,
                    backend_type=entry.transport,
                    error="Already exists in config",
                )
            )
            continue

        try:
            backend = _entry_to_backend(entry, catalog_id=cid)
        except (ValueError, ValidationError) as exc:
            result.items.append(
                CatalogItemResult(
                    name=entry.name,
                    status=CatalogEntryStatus.FAILED,
                    backend_type=entry.transport,
                    error=str(exc),
                )
            )
            continue

        # Optional health check
        if health_check is not None:
            try:
                healthy = health_check(entry.name, backend)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health check error for '%s': %s", entry.name, exc)
                healthy = False

            if not healthy:
                result.items.append(
                    CatalogItemResult(
                        name=entry.name,
                        status=CatalogEntryStatus.HEALTH_FAILED,
                        backend_type=entry.transport,
                        error="Health check failed",
                    )
                )
                continue

        config.backends[entry.name] = backend
        existing_names.add(entry.name)
        result.items.append(
            CatalogItemResult(
                name=entry.name,
                status=CatalogEntryStatus.ADDED,
                backend_type=entry.transport,
            )
        )

    logger.info("Catalog commit: %s", result.summary())
    return result
