"""Tests for container security guards in _build_create_args.

Covers CNTR-02/SEC-08: enforcement of DANGEROUS_DOCKER_FLAGS denylist
on the extra_args field of Docker container backend configuration.
"""

from __future__ import annotations

import pytest

from argus_mcp.bridge.container.wrapper import _build_create_args


def _base_kwargs(**overrides):
    """Return baseline keyword args for _build_create_args, with overrides."""
    base = {
        "image_tag": "test-image:latest",
        "runtime_args": [],
        "env": None,
        "network": "none",
        "memory": "512m",
        "cpus": "1",
    }
    base.update(overrides)
    return base


def test_extra_args_clean_passes():
    """Benign flags like --memory should pass through without raising."""
    args = _build_create_args(**_base_kwargs(extra_args=["--memory", "512m"]))
    assert "--memory" in args
    assert "512m" in args


def test_extra_args_denylist_raises():
    """--privileged must be rejected with RuntimeError mentioning 'privileged'."""
    with pytest.raises(RuntimeError, match="privileged"):
        _build_create_args(**_base_kwargs(extra_args=["--privileged"]))


def test_extra_args_denylist_network_host():
    """--network=host (= form) must be rejected by the denylist guard."""
    with pytest.raises(RuntimeError):
        _build_create_args(**_base_kwargs(extra_args=["--network=host"]))


def test_extra_args_empty():
    """Empty extra_args list must not raise."""
    args = _build_create_args(**_base_kwargs(extra_args=[]))
    assert isinstance(args, list)


def test_extra_args_none():
    """Omitted extra_args (None default) must not raise."""
    args = _build_create_args(**_base_kwargs())
    assert isinstance(args, list)
