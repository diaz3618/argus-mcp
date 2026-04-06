"""Structured audit event logger.

Writes JSON-line audit events to a dedicated file with rotation.
Also emits events via the standard ``logging`` infrastructure so they
can be picked up by the middleware and TUI.
"""

from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from argus_mcp.audit.models import AuditEvent
from argus_mcp.constants import AUDIT_BACKUP_COUNT, AUDIT_MAX_BYTES

logger = logging.getLogger(__name__)

# Rust-accelerated serialization (optional)
try:
    from audit_rs import serialize_audit_dict as _rust_serialize_dict
    from audit_rs import serialize_audit_event as _rust_serialize_event

    _USE_RUST = True
    logger.debug("Rust audit serializer loaded")
except ImportError:
    _USE_RUST = False
    _rust_serialize_event = None
    _rust_serialize_dict = None

logger = logging.getLogger(__name__)

# Custom log level — always enabled (NIST requirement: audit cannot be silenced)
AUDIT_LEVEL = 35  # between WARNING (30) and ERROR (40)
logging.addLevelName(AUDIT_LEVEL, "AUDIT")

DEFAULT_AUDIT_DIR = "logs"
DEFAULT_AUDIT_FILE = "audit.jsonl"


class AuditLogger:
    """JSON-line audit event writer with file rotation.

    Parameters
    ----------
    log_dir:
        Directory for the audit log file.
    filename:
        Name of the audit log file.
    max_bytes:
        Maximum file size before rotation.
    backup_count:
        Number of rotated files to keep.
    enabled:
        Whether to actually write events.
    """

    def __init__(
        self,
        *,
        log_dir: str = DEFAULT_AUDIT_DIR,
        filename: str = DEFAULT_AUDIT_FILE,
        max_bytes: int = AUDIT_MAX_BYTES,
        backup_count: int = AUDIT_BACKUP_COUNT,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._file_handler: Optional[RotatingFileHandler] = None
        self._audit_logger = logging.getLogger("argus_mcp.audit")
        self._audit_logger.setLevel(AUDIT_LEVEL)

        if enabled:
            os.makedirs(log_dir, exist_ok=True)
            filepath = os.path.join(log_dir, filename)  # nosemgrep: injection-path-traversal-join
            self._file_handler = RotatingFileHandler(
                filepath,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            self._file_handler.setLevel(AUDIT_LEVEL)
            # Raw JSON — no formatter wrapping
            self._file_handler.setFormatter(logging.Formatter("%(message)s"))
            self._audit_logger.addHandler(self._file_handler)
            logger.info(
                "Audit logger initialized: %s (max %d MB, %d backups)",
                filepath,
                max_bytes // (1024 * 1024),
                backup_count,
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def emit(self, event: AuditEvent) -> None:
        """Write an audit event as a JSON line."""
        if not self._enabled:
            return
        try:
            if _USE_RUST:
                line = _rust_serialize_event(
                    timestamp=event.timestamp,
                    event_type=event.event_type,
                    event_id=event.event_id,
                    method=event.target.method,
                    capability_name=event.target.capability_name,
                    status=event.outcome.status,
                    latency_ms=event.outcome.latency_ms,
                    session_id=event.source.session_id,
                    client_ip=event.source.client_ip,
                    user_id=event.source.user_id,
                    backend=event.target.backend,
                    original_name=event.target.original_name,
                    error=event.outcome.error,
                    error_type=event.outcome.error_type,
                    metadata=event.metadata if event.metadata else None,
                )
            else:
                line = event.model_dump_json()
            self._audit_logger.log(AUDIT_LEVEL, line)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to emit audit event")

    def emit_dict(self, data: dict[str, Any]) -> None:
        """Write a raw dict as a JSON line (for non-model events)."""
        if not self._enabled:
            return
        try:
            if _USE_RUST:
                line = _rust_serialize_dict(data)
            else:
                line = json.dumps(data, default=str, separators=(",", ":"))
            self._audit_logger.log(AUDIT_LEVEL, line)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to emit audit dict")

    def close(self) -> None:
        """Close the file handler."""
        if self._file_handler is not None:
            self._file_handler.close()
            self._audit_logger.removeHandler(self._file_handler)
            self._file_handler = None
