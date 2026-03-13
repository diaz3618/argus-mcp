"""Configuration import — merge external config into an existing ArgusConfig.

Supports conflict strategies (skip, update, rename, fail), dry-run
validation, and selective filtering.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import yaml
from pydantic import BaseModel, Field, ValidationError

from argus_mcp.config.schema import ArgusConfig, BackendConfig, RegistryEntryConfig
from argus_mcp.config.schema_backends import (
    SseBackendConfig,
    StdioBackendConfig,
    StreamableHttpBackendConfig,
)

logger = logging.getLogger(__name__)

# Maximum import payload size (bytes) — prevent DoS via huge payloads.
MAX_IMPORT_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
# Maximum number of backends in a single import batch.
MAX_IMPORT_BACKENDS: int = 200
# Maximum number of registries in a single import batch.
MAX_IMPORT_REGISTRIES: int = 50


class ConflictStrategy(str, Enum):
    """How to handle naming conflicts during import."""

    SKIP = "skip"
    UPDATE = "update"
    RENAME = "rename"
    FAIL = "fail"


class ImportItemStatus(str, Enum):
    """Status of an individual imported item."""

    ADDED = "added"
    UPDATED = "updated"
    SKIPPED = "skipped"
    RENAMED = "renamed"
    FAILED = "failed"


class ImportItemResult(BaseModel):
    """Result for a single imported entity."""

    name: str
    entity_type: str
    status: ImportItemStatus
    new_name: Optional[str] = None
    error: Optional[str] = None


class ImportResult(BaseModel):
    """Aggregate result of an import operation."""

    import_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    imported_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    dry_run: bool = False
    conflict_strategy: str = "skip"
    items: List[ImportItemResult] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    @property
    def added_count(self) -> int:
        return sum(1 for i in self.items if i.status == ImportItemStatus.ADDED)

    @property
    def updated_count(self) -> int:
        return sum(1 for i in self.items if i.status == ImportItemStatus.UPDATED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for i in self.items if i.status == ImportItemStatus.SKIPPED)

    @property
    def failed_count(self) -> int:
        return sum(1 for i in self.items if i.status == ImportItemStatus.FAILED)

    @property
    def success(self) -> bool:
        return self.failed_count == 0 and not self.errors

    def summary(self) -> str:
        return (
            f"+{self.added_count} ~{self.updated_count} ={self.skipped_count} !{self.failed_count}"
        )


class ImportValidationError(Exception):
    """Raised when imported data fails validation."""


def _generate_rename(name: str, existing_names: Set[str]) -> str:
    """Generate a unique name by appending a numeric suffix."""
    for i in range(1, 1000):
        candidate = f"{name}_{i}"
        if candidate not in existing_names:
            return candidate
    raise ImportValidationError(f"Cannot generate unique rename for '{name}' after 999 attempts")


def _parse_backend(name: str, raw: Dict[str, Any]) -> BackendConfig:
    """Parse and validate a single backend config from raw dict.

    Returns a validated Pydantic model.
    """
    btype = raw.get("type")
    if btype == "stdio":
        return StdioBackendConfig(**raw)
    elif btype == "sse":
        return SseBackendConfig(**raw)
    elif btype == "streamable-http":
        return StreamableHttpBackendConfig(**raw)
    else:
        raise ImportValidationError(f"Backend '{name}': unsupported type '{btype}'")


def _validate_import_limits(
    payload: Dict[str, Any],
    *,
    max_backends: int = MAX_IMPORT_BACKENDS,
    max_registries: int = MAX_IMPORT_REGISTRIES,
) -> List[str]:
    """Check bulk import size limits.  Returns a list of errors."""
    errors: List[str] = []
    backends = payload.get("backends", {})
    if isinstance(backends, dict) and len(backends) > max_backends:
        errors.append(f"Too many backends: {len(backends)} exceeds limit {max_backends}")
    registries = payload.get("registries", [])
    if isinstance(registries, list) and len(registries) > max_registries:
        errors.append(f"Too many registries: {len(registries)} exceeds limit {max_registries}")
    return errors


def parse_import_payload(
    raw_yaml: str,
    *,
    max_size_bytes: int = MAX_IMPORT_SIZE_BYTES,
) -> Dict[str, Any]:
    """Parse and validate a YAML import payload.

    Parameters
    ----------
    raw_yaml:
        The YAML string to parse.
    max_size_bytes:
        Maximum allowed payload size in bytes.

    Returns
    -------
    dict
        Parsed YAML data.

    Raises
    ------
    ImportValidationError
        If the payload is invalid, too large, or fails basic structure checks.
    """
    if len(raw_yaml.encode("utf-8")) > max_size_bytes:
        raise ImportValidationError(f"Import payload too large: exceeds {max_size_bytes} bytes")

    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise ImportValidationError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ImportValidationError("Import payload must be a YAML mapping")

    return data


def import_config(
    target: ArgusConfig,
    payload: Dict[str, Any],
    *,
    conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP,
    dry_run: bool = False,
    entity_types: Optional[Set[str]] = None,
    max_backends: int = MAX_IMPORT_BACKENDS,
    max_registries: int = MAX_IMPORT_REGISTRIES,
) -> ImportResult:
    """Import configuration from a parsed payload into *target*.

    Parameters
    ----------
    target:
        The existing :class:`ArgusConfig` to merge into.
        Mutated in-place unless *dry_run* is ``True``.
    payload:
        Parsed dict (from :func:`parse_import_payload`).
    conflict_strategy:
        How to handle naming collisions.
    dry_run:
        If ``True``, validate and report without modifying *target*.
    entity_types:
        Which entity sections to import.  Defaults to all present.
    max_backends:
        Maximum backends allowed in a single import.
    max_registries:
        Maximum registries allowed in a single import.

    Returns
    -------
    ImportResult
        Summary of the import operation.
    """
    if entity_types is None:
        entity_types = {"backends", "registries", "feature_flags", "plugins"}

    result = ImportResult(
        dry_run=dry_run,
        conflict_strategy=conflict_strategy.value,
    )

    limit_errors = _validate_import_limits(
        payload,
        max_backends=max_backends,
        max_registries=max_registries,
    )
    if limit_errors:
        result.errors.extend(limit_errors)
        return result

    if "backends" in entity_types and "backends" in payload:
        raw_backends = payload["backends"]
        if isinstance(raw_backends, dict):
            existing_names = set(target.backends.keys())
            for name, raw_cfg in raw_backends.items():
                if not isinstance(raw_cfg, dict):
                    result.items.append(
                        ImportItemResult(
                            name=name,
                            entity_type="backend",
                            status=ImportItemStatus.FAILED,
                            error="Backend config must be a mapping",
                        )
                    )
                    continue

                # Validate the backend config
                try:
                    validated = _parse_backend(name, raw_cfg)
                except (ValidationError, ImportValidationError) as exc:
                    result.items.append(
                        ImportItemResult(
                            name=name,
                            entity_type="backend",
                            status=ImportItemStatus.FAILED,
                            error=str(exc),
                        )
                    )
                    continue

                # Handle conflicts
                if name in existing_names:
                    if conflict_strategy == ConflictStrategy.FAIL:
                        result.items.append(
                            ImportItemResult(
                                name=name,
                                entity_type="backend",
                                status=ImportItemStatus.FAILED,
                                error=f"Backend '{name}' already exists",
                            )
                        )
                        continue
                    elif conflict_strategy == ConflictStrategy.SKIP:
                        result.items.append(
                            ImportItemResult(
                                name=name,
                                entity_type="backend",
                                status=ImportItemStatus.SKIPPED,
                            )
                        )
                        continue
                    elif conflict_strategy == ConflictStrategy.RENAME:
                        new_name = _generate_rename(name, existing_names)
                        if not dry_run:
                            target.backends[new_name] = validated
                        existing_names.add(new_name)
                        result.items.append(
                            ImportItemResult(
                                name=name,
                                entity_type="backend",
                                status=ImportItemStatus.RENAMED,
                                new_name=new_name,
                            )
                        )
                        continue
                    elif conflict_strategy == ConflictStrategy.UPDATE:
                        if not dry_run:
                            target.backends[name] = validated
                        result.items.append(
                            ImportItemResult(
                                name=name,
                                entity_type="backend",
                                status=ImportItemStatus.UPDATED,
                            )
                        )
                        continue

                # No conflict — add
                if not dry_run:
                    target.backends[name] = validated
                existing_names.add(name)
                result.items.append(
                    ImportItemResult(
                        name=name,
                        entity_type="backend",
                        status=ImportItemStatus.ADDED,
                    )
                )

    if "registries" in entity_types and "registries" in payload:
        raw_registries = payload["registries"]
        if isinstance(raw_registries, list):
            existing_reg_names = {r.name for r in target.registries}
            for idx, raw_reg in enumerate(raw_registries):
                if not isinstance(raw_reg, dict):
                    result.items.append(
                        ImportItemResult(
                            name=f"registry[{idx}]",
                            entity_type="registry",
                            status=ImportItemStatus.FAILED,
                            error="Registry entry must be a mapping",
                        )
                    )
                    continue

                reg_name = raw_reg.get("name", f"registry_{idx}")
                try:
                    validated_reg = RegistryEntryConfig(**raw_reg)
                except ValidationError as exc:
                    result.items.append(
                        ImportItemResult(
                            name=reg_name,
                            entity_type="registry",
                            status=ImportItemStatus.FAILED,
                            error=str(exc),
                        )
                    )
                    continue

                if reg_name in existing_reg_names:
                    if conflict_strategy == ConflictStrategy.FAIL:
                        result.items.append(
                            ImportItemResult(
                                name=reg_name,
                                entity_type="registry",
                                status=ImportItemStatus.FAILED,
                                error=f"Registry '{reg_name}' already exists",
                            )
                        )
                        continue
                    elif conflict_strategy == ConflictStrategy.SKIP:
                        result.items.append(
                            ImportItemResult(
                                name=reg_name,
                                entity_type="registry",
                                status=ImportItemStatus.SKIPPED,
                            )
                        )
                        continue
                    elif conflict_strategy == ConflictStrategy.UPDATE:
                        if not dry_run:
                            # Replace existing
                            target.registries = [
                                validated_reg if r.name == reg_name else r
                                for r in target.registries
                            ]
                        result.items.append(
                            ImportItemResult(
                                name=reg_name,
                                entity_type="registry",
                                status=ImportItemStatus.UPDATED,
                            )
                        )
                        continue
                    elif conflict_strategy == ConflictStrategy.RENAME:
                        new_name = _generate_rename(reg_name, existing_reg_names)
                        validated_reg = validated_reg.model_copy(update={"name": new_name})
                        if not dry_run:
                            target.registries.append(validated_reg)
                        existing_reg_names.add(new_name)
                        result.items.append(
                            ImportItemResult(
                                name=reg_name,
                                entity_type="registry",
                                status=ImportItemStatus.RENAMED,
                                new_name=new_name,
                            )
                        )
                        continue

                # No conflict — add
                if not dry_run:
                    target.registries.append(validated_reg)
                existing_reg_names.add(reg_name)
                result.items.append(
                    ImportItemResult(
                        name=reg_name,
                        entity_type="registry",
                        status=ImportItemStatus.ADDED,
                    )
                )

    if "feature_flags" in entity_types and "feature_flags" in payload:
        raw_flags = payload["feature_flags"]
        if isinstance(raw_flags, dict):
            for flag_name, flag_value in raw_flags.items():
                if not isinstance(flag_value, bool):
                    result.items.append(
                        ImportItemResult(
                            name=flag_name,
                            entity_type="feature_flag",
                            status=ImportItemStatus.FAILED,
                            error="Feature flag value must be boolean",
                        )
                    )
                    continue

                if flag_name in target.feature_flags:
                    if conflict_strategy == ConflictStrategy.SKIP:
                        result.items.append(
                            ImportItemResult(
                                name=flag_name,
                                entity_type="feature_flag",
                                status=ImportItemStatus.SKIPPED,
                            )
                        )
                        continue
                    elif conflict_strategy == ConflictStrategy.FAIL:
                        result.items.append(
                            ImportItemResult(
                                name=flag_name,
                                entity_type="feature_flag",
                                status=ImportItemStatus.FAILED,
                                error=f"Feature flag '{flag_name}' already exists",
                            )
                        )
                        continue

                status = (
                    ImportItemStatus.UPDATED
                    if flag_name in target.feature_flags
                    else ImportItemStatus.ADDED
                )
                if not dry_run:
                    target.feature_flags[flag_name] = flag_value
                result.items.append(
                    ImportItemResult(
                        name=flag_name,
                        entity_type="feature_flag",
                        status=status,
                    )
                )

    logger.info(
        "Config import completed: id=%s, dry_run=%s, strategy=%s, summary=%s",
        result.import_id,
        dry_run,
        conflict_strategy.value,
        result.summary(),
    )
    return result
