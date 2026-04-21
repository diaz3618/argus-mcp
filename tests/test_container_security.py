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


# ---------------------------------------------------------------------------
# CNTR-03: RuntimeFactory.reset() production guard
# ---------------------------------------------------------------------------

import os
from unittest.mock import patch

from argus_mcp.bridge.container.runtime import RuntimeFactory


def test_reset_blocked_in_production():
    """reset() must raise RuntimeError when ARGUS_TEST_MODE is not set to '1'."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ARGUS_TEST_MODE", None)
        with pytest.raises(RuntimeError, match="ARGUS_TEST_MODE"):
            RuntimeFactory.reset()


def test_reset_allowed_in_test_mode():
    """reset() must succeed silently when ARGUS_TEST_MODE='1'."""
    with patch.dict(os.environ, {"ARGUS_TEST_MODE": "1"}):
        RuntimeFactory.reset()  # must not raise


# ---------------------------------------------------------------------------
# BRIDGE-05: middleware None-return assertion in build_chain()._wrap
# ---------------------------------------------------------------------------

import pytest as _pytest

from argus_mcp.bridge.middleware.chain import build_chain


@_pytest.mark.asyncio
async def test_middleware_none_return_raises():
    """A middleware that returns None must trigger AssertionError naming the class."""

    class BadMiddleware:
        async def __call__(self, ctx, next_handler):
            return None  # buggy: forgot to return next_handler result

        def __repr__(self):
            return "BadMiddleware"

    async def terminal(ctx):
        return {"ok": True}

    chain = build_chain([BadMiddleware()], terminal)
    with _pytest.raises(AssertionError, match="BadMiddleware"):
        await chain({})


@_pytest.mark.asyncio
async def test_middleware_valid_return_passes():
    """A correct middleware returning the next_handler result must succeed."""

    class GoodMiddleware:
        async def __call__(self, ctx, next_handler):
            return await next_handler(ctx)

    async def terminal(ctx):
        return {"ok": True}

    chain = build_chain([GoodMiddleware()], terminal)
    result = await chain({})
    assert result == {"ok": True}
