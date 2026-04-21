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


# ---------------------------------------------------------------------------
# CNTR-01: env-var secret-pattern warning in _build_create_args
# ---------------------------------------------------------------------------

import logging


def test_env_secret_warns(caplog):
    """An env value matching the base64/token pattern must emit a warning
    that names the key but NOT the value."""
    secret = "A" * 40  # 40 chars, matches ^[A-Za-z0-9+/]{32,}={0,2}$
    with caplog.at_level(logging.WARNING, logger="argus_mcp.bridge.container.wrapper"):
        _build_create_args(**_base_kwargs(env={"API_TOKEN": secret}))
    matching = [r for r in caplog.records if "API_TOKEN" in r.getMessage()]
    assert matching, "expected a warning mentioning API_TOKEN"
    for rec in matching:
        msg = rec.getMessage()
        assert secret not in msg, "warning must not contain the secret value"


def test_env_short_value_no_warn(caplog):
    """Values shorter than 32 chars must not trigger the secret warning."""
    with caplog.at_level(logging.WARNING, logger="argus_mcp.bridge.container.wrapper"):
        _build_create_args(**_base_kwargs(env={"SHORT": "abc123"}))
    assert not any("secret" in r.getMessage().lower() for r in caplog.records)


def test_env_no_env_no_warn(caplog):
    """When env is None, no secret warnings must be emitted."""
    with caplog.at_level(logging.WARNING, logger="argus_mcp.bridge.container.wrapper"):
        _build_create_args(**_base_kwargs(env=None))
    assert not any("secret" in r.getMessage().lower() for r in caplog.records)


def test_env_warning_key_only(caplog):
    """Warning message must reference the key name and not the secret value."""
    secret = "B" * 50
    with caplog.at_level(logging.WARNING, logger="argus_mcp.bridge.container.wrapper"):
        _build_create_args(**_base_kwargs(env={"MY_KEY": secret}))
    secret_warnings = [r for r in caplog.records if "secret" in r.getMessage().lower()]
    assert secret_warnings, "expected at least one secret warning"
    for rec in secret_warnings:
        assert "MY_KEY" in rec.getMessage()
        assert secret not in rec.getMessage()


def test_env_non_base64_no_warn(caplog):
    """Long values containing chars outside [A-Za-z0-9+/=] must not warn."""
    # 40 chars but contains '-' and '_' which are NOT in the base64 alphabet
    value = "not-a-base64-token_with-dashes-and-unders"
    assert len(value) >= 32
    with caplog.at_level(logging.WARNING, logger="argus_mcp.bridge.container.wrapper"):
        _build_create_args(**_base_kwargs(env={"WEIRD": value}))
    assert not any("secret" in r.getMessage().lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# _active_containers scope refactor: per-ClientManager isolation
# ---------------------------------------------------------------------------

from argus_mcp.bridge.container.wrapper import (
    cleanup_all_containers,
    cleanup_container,
)


@_pytest.mark.asyncio
async def test_active_containers_isolated():
    """Two separate active_containers dicts must remain independent — no
    module-level shared state."""
    dict_a: dict = {"svr-a": ("docker", "cid-a")}
    dict_b: dict = {"svr-b": ("docker", "cid-b")}

    # The two dicts are distinct objects; mutating one must not affect the other.
    assert dict_a is not dict_b
    assert "svr-a" not in dict_b
    assert "svr-b" not in dict_a

    # Module must NOT expose a shared _active_containers global anymore.
    import argus_mcp.bridge.container.wrapper as wrapper_mod

    assert not hasattr(wrapper_mod, "_active_containers"), (
        "_active_containers module-level dict must be removed"
    )


@_pytest.mark.asyncio
async def test_cleanup_uses_passed_dict(monkeypatch):
    """cleanup_container must operate on the passed-in active_containers dict."""
    active: dict = {"svr-x": ("docker", "cid-x")}

    async def fake_remove(*a, **kw):
        return None

    monkeypatch.setattr(
        "argus_mcp.bridge.container.wrapper._remove_container_by_id",
        fake_remove,
        raising=False,
    )
    monkeypatch.setattr(
        "argus_mcp.bridge.container.wrapper._remove_container_by_name",
        fake_remove,
        raising=False,
    )

    await cleanup_container("svr-x", active_containers=active)
    assert "svr-x" not in active, "entry must be removed from passed-in dict"


@_pytest.mark.asyncio
async def test_cleanup_all_uses_passed_dict(monkeypatch):
    """cleanup_all_containers must drain the passed-in dict, not a global one."""
    active: dict = {
        "svr-1": ("docker", "cid-1"),
        "svr-2": ("docker", "cid-2"),
    }

    async def fake_remove(*a, **kw):
        return None

    monkeypatch.setattr(
        "argus_mcp.bridge.container.wrapper._remove_container_by_id",
        fake_remove,
        raising=False,
    )
    monkeypatch.setattr(
        "argus_mcp.bridge.container.wrapper._remove_container_by_name",
        fake_remove,
        raising=False,
    )

    await cleanup_all_containers(active_containers=active)
    assert active == {}, "passed-in dict must be drained"
