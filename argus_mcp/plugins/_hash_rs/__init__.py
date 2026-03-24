"""Rust-accelerated JSON+SHA256 cache key hashing with Python fallback."""

from __future__ import annotations

RUST_AVAILABLE = False

try:
    from hash_rs import json_sha256

    RUST_AVAILABLE = True
except ImportError:
    json_sha256 = None

__all__ = ["json_sha256", "RUST_AVAILABLE"]
