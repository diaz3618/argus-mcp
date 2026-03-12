"""Rust-accelerated capability filter with Python fallback."""

from __future__ import annotations

RUST_AVAILABLE = False

try:
    from filter_rs import RustCapabilityFilter

    RUST_AVAILABLE = True
except ImportError:
    RustCapabilityFilter = None

__all__ = ["RustCapabilityFilter", "RUST_AVAILABLE"]
