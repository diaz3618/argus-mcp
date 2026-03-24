"""Rust-accelerated YAML parsing with Python fallback."""

from __future__ import annotations

RUST_AVAILABLE = False

try:
    from yaml_rs import parse_yaml

    RUST_AVAILABLE = True
except ImportError:
    parse_yaml = None

__all__ = ["parse_yaml", "RUST_AVAILABLE"]
