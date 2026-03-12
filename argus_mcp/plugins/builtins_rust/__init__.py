"""Rust-accelerated PII filter and secrets scanner with Python fallback."""

from __future__ import annotations

RUST_AVAILABLE = False

try:
    from security_plugins_rs import RustPiiFilter, RustSecretsScanner

    RUST_AVAILABLE = True
except ImportError:
    RustPiiFilter = None
    RustSecretsScanner = None

__all__ = ["RustPiiFilter", "RustSecretsScanner", "RUST_AVAILABLE"]
