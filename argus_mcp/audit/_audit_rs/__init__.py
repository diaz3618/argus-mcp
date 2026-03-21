"""Rust-accelerated audit event serialization with Python fallback."""

from __future__ import annotations

RUST_AVAILABLE = False

try:
    from audit_rs import serialize_audit_dict, serialize_audit_event

    RUST_AVAILABLE = True
except ImportError:
    serialize_audit_event = None
    serialize_audit_dict = None

__all__ = ["serialize_audit_event", "serialize_audit_dict", "RUST_AVAILABLE"]
