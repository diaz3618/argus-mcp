"""Rust-accelerated token cache with secure erasure and Python fallback."""

from __future__ import annotations

RUST_AVAILABLE = False

try:
    from token_cache_rs import RustTokenCache as TokenCache

    RUST_AVAILABLE = True
except ImportError:
    from argus_mcp.bridge.auth.token_cache import TokenCache

__all__ = ["TokenCache", "RUST_AVAILABLE"]
