#!/usr/bin/env python3
"""Benchmark: Rust vs Python paths for Phase 6 integration.

Measures Python-baseline latency for each of the 4 Rust-bridged modules.
When Rust extensions are compiled (``maturin develop``), also benchmarks
the Rust path and prints a comparison table.

Usage::

    python tools/bench_rust_vs_python.py
"""

from __future__ import annotations

import time

ITERATIONS = 1000


def _percentiles(timings: list[float]) -> tuple[float, float, float]:
    """Return (p50, p95, p99) in microseconds."""
    s = sorted(timings)
    n = len(s)
    return (
        s[int(n * 0.50)] * 1e6,
        s[int(n * 0.95)] * 1e6,
        s[int(n * 0.99)] * 1e6,
    )


def _bench(fn, *, warmup: int = 50) -> tuple[float, float, float]:
    """Benchmark *fn* and return (p50, p95, p99) in µs."""
    for _ in range(warmup):
        fn()
    timings = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        fn()
        timings.append(time.perf_counter() - start)
    return _percentiles(timings)


#  1. Capability Filter
def bench_filter_python() -> tuple[float, float, float]:
    from argus_mcp.bridge.filter import CapabilityFilter

    f = CapabilityFilter(
        allow=["mcp_*", "tool_*", "echo", "search_*"],
        deny=["mcp_internal_*", "tool_debug_*"],
    )
    names = [f"mcp_server_{i}" for i in range(20)] + [
        "mcp_internal_secret",
        "tool_debug_foo",
        "echo",
        "unknown",
    ]

    def run():
        for n in names:
            f.is_allowed(n)

    return _bench(run)


def bench_filter_rust() -> tuple[float, float, float] | None:
    from argus_mcp.bridge._filter_rs import RUST_AVAILABLE, RustCapabilityFilter

    if not RUST_AVAILABLE or RustCapabilityFilter is None:
        return None

    f = RustCapabilityFilter(
        allow=["mcp_*", "tool_*", "echo", "search_*"],
        deny=["mcp_internal_*", "tool_debug_*"],
    )
    names = [f"mcp_server_{i}" for i in range(20)] + [
        "mcp_internal_secret",
        "tool_debug_foo",
        "echo",
        "unknown",
    ]

    def run():
        for n in names:
            f.is_allowed(n)

    return _bench(run)


#  2. Circuit Breaker
def bench_cb_python() -> tuple[float, float, float]:
    from argus_mcp.bridge.health.circuit_breaker import CircuitBreaker

    def run():
        cb = CircuitBreaker("bench", failure_threshold=3, cooldown_seconds=0.001)
        for _ in range(5):
            cb.record_success()
        for _ in range(3):
            cb.record_failure()
        _ = cb.allows_request
        _ = cb.to_dict()
        cb.reset()

    return _bench(run)


def bench_cb_rust() -> tuple[float, float, float] | None:
    from argus_mcp.bridge.health._circuit_breaker_rs import (
        RUST_AVAILABLE,
        CircuitBreaker,
    )

    if not RUST_AVAILABLE:
        return None

    def run():
        cb = CircuitBreaker("bench", failure_threshold=3, cooldown_seconds=0.001)
        for _ in range(5):
            cb.record_success()
        for _ in range(3):
            cb.record_failure()
        _ = cb.allows_request
        _ = cb.to_dict()
        cb.reset()

    return _bench(run)


#  3. Token Cache
def bench_tc_python() -> tuple[float, float, float]:
    from argus_mcp.bridge.auth.token_cache import TokenCache

    def run():
        tc = TokenCache(expiry_buffer=30)
        tc.set("tok_abc123xyz", 3600)
        _ = tc.valid
        _ = tc.get()
        tc.invalidate()
        _ = tc.valid

    return _bench(run)


def bench_tc_rust() -> tuple[float, float, float] | None:
    from argus_mcp.bridge.auth._token_cache_rs import RUST_AVAILABLE, TokenCache

    if not RUST_AVAILABLE:
        return None

    def run():
        tc = TokenCache(expiry_buffer=30)
        tc.set("tok_abc123xyz", 3600)
        _ = tc.valid
        _ = tc.get()
        tc.invalidate()
        _ = tc.valid

    return _bench(run)


#  4. PII Filter

SAMPLE_TEXT = (
    "Contact john.doe@example.com or call 555-123-4567. "
    "SSN is 123-45-6789. Card: 4111 1111 1111 1111. "
    "Passport: AB1234567."
)


def bench_pii_python() -> tuple[float, float, float]:
    from argus_mcp.plugins.builtins.pii_filter import PiiFilterPlugin
    from argus_mcp.plugins.models import PluginConfig

    cfg = PluginConfig(name="pii_filter", enabled=True, settings={})
    plugin = PiiFilterPlugin(cfg)
    plugin._rust_engine = None  # force Python path

    def run():
        plugin._mask_string(SAMPLE_TEXT)

    return _bench(run)


def bench_pii_rust() -> tuple[float, float, float] | None:
    from argus_mcp.plugins.builtins_rust import RUST_AVAILABLE, RustPiiFilter

    if not RUST_AVAILABLE or RustPiiFilter is None:
        return None

    engine = RustPiiFilter()

    def run():
        engine.mask_string(SAMPLE_TEXT)

    return _bench(run)


#  5. Secrets Scanner

SECRET_TEXT = (
    "key=AKIAIOSFODNN7EXAMPLE rest. "
    "bearer: Bearer eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3ODkw.SflKxwRJSMeKKF2QT4fwpM "
    "token: ghp_ABCDEFghijklmnopqrstuvwxyz1234567890 safe text here."
)


def bench_secrets_python() -> tuple[float, float, float]:
    from argus_mcp.plugins.builtins.secrets_detection import (
        SecretsDetectionPlugin,
    )
    from argus_mcp.plugins.models import PluginConfig

    cfg = PluginConfig(
        name="secrets_detection",
        enabled=True,
        settings={"block": False},
    )
    plugin = SecretsDetectionPlugin(cfg)
    plugin._rust_engine = None  # force Python path

    from argus_mcp.plugins.builtins.secrets_detection import _PATTERNS, _REDACTION

    def run():
        text = SECRET_TEXT
        for _, pattern in _PATTERNS:
            text = pattern.sub(_REDACTION, text)

    return _bench(run)


def bench_secrets_rust() -> tuple[float, float, float] | None:
    from argus_mcp.plugins.builtins_rust import RUST_AVAILABLE, RustSecretsScanner

    if not RUST_AVAILABLE or RustSecretsScanner is None:
        return None

    engine = RustSecretsScanner()

    def run():
        engine.redact(SECRET_TEXT)

    return _bench(run)


#  Main

#  6. Audit Event Serialization

AUDIT_KWARGS = dict(
    timestamp="2024-01-15T10:30:00Z",
    event_type="mcp_operation",
    event_id="evt-001",
    method="tools/call",
    capability_name="search",
    status="success",
    latency_ms=42.5,
    session_id="sess-abc123",
    client_ip="10.0.0.1",
    user_id="user42",
    backend="server-alpha",
    original_name="search_docs",
    error=None,
    error_type=None,
    metadata={"model": "gpt-4", "tokens": 150},
)


def bench_audit_python() -> tuple[float, float, float]:
    import json

    def run():
        json.dumps(AUDIT_KWARGS, default=str)

    return _bench(run)


def bench_audit_rust() -> tuple[float, float, float] | None:
    from argus_mcp.audit._audit_rs import RUST_AVAILABLE, serialize_audit_event

    if not RUST_AVAILABLE or serialize_audit_event is None:
        return None

    def run():
        serialize_audit_event(**AUDIT_KWARGS)

    return _bench(run)


#  7. Cache Key Hashing (JSON + SHA256)
def bench_hash_python() -> tuple[float, float, float]:
    import hashlib
    import json

    def run():
        data = {"server": "alpha", "capability": "search", "arguments": {"q": "hello", "limit": 10}}
        raw = json.dumps(data, sort_keys=True)
        hashlib.sha256(raw.encode()).hexdigest()

    return _bench(run)


def bench_hash_rust() -> tuple[float, float, float] | None:
    from argus_mcp.plugins._hash_rs import RUST_AVAILABLE, json_sha256

    if not RUST_AVAILABLE or json_sha256 is None:
        return None

    def run():
        json_sha256("alpha", "search", {"q": "hello", "limit": 10})

    return _bench(run)


#  8. YAML Parsing

YAML_SAMPLE = """
servers:
  alpha:
    url: "http://localhost:8080"
    transport: stdio
    capabilities:
      - search
      - read
    metadata:
      version: "1.2.3"
      tags: [prod, stable]
  beta:
    url: "http://localhost:9090"
    transport: sse
    capabilities:
      - write
plugins:
  pii_filter:
    enabled: true
    settings:
      mask: "***"
  rate_limiter:
    enabled: false
"""


def bench_yaml_python() -> tuple[float, float, float]:
    import yaml

    def run():
        yaml.safe_load(YAML_SAMPLE)

    return _bench(run)


def bench_yaml_rust() -> tuple[float, float, float] | None:
    from argus_mcp.config._yaml_rs import RUST_AVAILABLE, parse_yaml

    if not RUST_AVAILABLE or parse_yaml is None:
        return None

    def run():
        parse_yaml(YAML_SAMPLE)

    return _bench(run)


#  Main (updated)
def main() -> None:
    print(f"Rust vs Python benchmark — {ITERATIONS} iterations each\n")

    benches = [
        ("CapabilityFilter (24 names)", bench_filter_python, bench_filter_rust),
        ("CircuitBreaker lifecycle", bench_cb_python, bench_cb_rust),
        ("TokenCache lifecycle", bench_tc_python, bench_tc_rust),
        ("PII Filter (multi-pattern)", bench_pii_python, bench_pii_rust),
        ("Secrets Scanner (redact)", bench_secrets_python, bench_secrets_rust),
        ("Audit Serialization", bench_audit_python, bench_audit_rust),
        ("Cache Key Hash (JSON+SHA256)", bench_hash_python, bench_hash_rust),
        ("YAML Parsing (config)", bench_yaml_python, bench_yaml_rust),
    ]

    header = f"{'Module':<32} {'Path':<8} {'p50 µs':>10} {'p95 µs':>10} {'p99 µs':>10}"
    print(header)
    print("-" * len(header))

    for label, py_fn, rs_fn in benches:
        py = py_fn()
        print(f"{label:<32} {'Python':<8} {py[0]:>10.1f} {py[1]:>10.1f} {py[2]:>10.1f}")

        rs = rs_fn()
        if rs is not None:
            speedup = py[0] / rs[0] if rs[0] > 0 else float("inf")
            print(
                f"{'':<32} {'Rust':<8} {rs[0]:>10.1f} {rs[1]:>10.1f} {rs[2]:>10.1f}"
                f"  ({speedup:.1f}x)"
            )
        else:
            print(f"{'':<32} {'Rust':<8} {'N/A':>10} {'N/A':>10} {'N/A':>10}  (not compiled)")

    print("\nNote: Rust extensions require 'maturin develop' in each crate directory.")


if __name__ == "__main__":
    main()
