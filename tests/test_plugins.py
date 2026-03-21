"""Tests for argus_mcp.plugins — Plugin framework core.

Covers:
- PluginContext: defaults, copy-on-write isolation, slots
- PluginConfig / PluginsConfig: validation, defaults, edge cases
- PluginBase: hook defaults are no-ops, lifecycle
- PluginRegistry: load_from_config, get_by_hook priority sorting, lifecycle
- PluginManager: run_hook priority ordering, timeout, error isolation by mode,
  condition matching, copy-on-write semantics, metadata aggregation
- PluginMiddleware: pre/post hook wiring, call_tool post-hook, method mapping
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.manager import PluginError, PluginManager
from argus_mcp.plugins.middleware import PluginMiddleware, _request_to_plugin_ctx
from argus_mcp.plugins.models import (
    ExecutionMode,
    PluginCondition,
    PluginConfig,
    PluginsConfig,
)
from argus_mcp.plugins.registry import _PLUGIN_CLASSES, PluginRegistry, register_plugin

# Helpers


def _make_config(
    name: str = "test-plugin",
    *,
    enabled: bool = True,
    priority: int = 100,
    timeout: float = 30.0,
    execution_mode: ExecutionMode = ExecutionMode.enforce_ignore_error,
    conditions: PluginCondition | None = None,
    settings: Dict[str, Any] | None = None,
) -> PluginConfig:
    return PluginConfig(
        name=name,
        enabled=enabled,
        priority=priority,
        timeout=timeout,
        execution_mode=execution_mode,
        conditions=conditions or PluginCondition(),
        settings=settings or {},
    )


class _NoopPlugin(PluginBase):
    """Minimal plugin that overrides nothing (all defaults)."""


class _PreInvokePlugin(PluginBase):
    """Plugin that overrides tool_pre_invoke to add metadata."""

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        ctx.metadata["pre_touched_by"] = self.name
        return ctx


class _PostInvokePlugin(PluginBase):
    """Plugin that overrides tool_post_invoke to transform results."""

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        ctx.metadata["post_touched_by"] = self.name
        ctx.result = f"modified:{ctx.result}"
        return ctx


class _SlowPlugin(PluginBase):
    """Plugin that sleeps forever (for timeout testing)."""

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        await asyncio.sleep(999)
        return ctx


class _ErrorPlugin(PluginBase):
    """Plugin that raises on every pre-invoke hook."""

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        raise ValueError("intentional plugin error")


class _ArgumentMutator(PluginBase):
    """Plugin that modifies arguments to test copy-on-write."""

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        ctx.arguments["injected"] = True
        return ctx


class _LifecyclePlugin(PluginBase):
    """Tracks on_load/on_unload calls."""

    loaded: bool = False
    unloaded: bool = False

    async def on_load(self) -> None:
        self.loaded = True

    async def on_unload(self) -> None:
        self.unloaded = True


# Fixtures


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure test plugin registrations don't leak between tests."""
    saved = dict(_PLUGIN_CLASSES)
    yield
    _PLUGIN_CLASSES.clear()
    _PLUGIN_CLASSES.update(saved)


# PluginContext


class TestPluginContext:
    def test_defaults(self) -> None:
        ctx = PluginContext(capability_name="echo", mcp_method="call_tool")
        assert ctx.capability_name == "echo"
        assert ctx.mcp_method == "call_tool"
        assert ctx.arguments == {}
        assert ctx.server_name == ""
        assert ctx.metadata == {}
        assert ctx.result is None

    def test_copy_isolation(self) -> None:
        ctx = PluginContext(
            capability_name="t",
            mcp_method="call_tool",
            arguments={"key": "val"},
            metadata={"m": 1},
        )
        clone = ctx.copy()
        clone.arguments["new"] = "data"
        clone.metadata["extra"] = True
        # Original unchanged
        assert "new" not in ctx.arguments
        assert "extra" not in ctx.metadata

    def test_slots(self) -> None:
        ctx = PluginContext(capability_name="t", mcp_method="m")
        with pytest.raises(AttributeError):
            ctx.non_existent_attr = 42  # type: ignore[attr-defined]


# PluginConfig / PluginsConfig


class TestPluginConfig:
    def test_defaults(self) -> None:
        cfg = PluginConfig(name="x")
        assert cfg.enabled is True
        assert cfg.execution_mode == ExecutionMode.enforce_ignore_error
        assert cfg.priority == 100
        assert cfg.timeout == 30.0
        assert cfg.conditions.servers == []
        assert cfg.settings == {}

    def test_execution_modes(self) -> None:
        for mode in ExecutionMode:
            cfg = PluginConfig(name="x", execution_mode=mode)
            assert cfg.execution_mode is mode

    def test_priority_boundaries(self) -> None:
        cfg_low = PluginConfig(name="a", priority=0)
        cfg_high = PluginConfig(name="b", priority=10000)
        assert cfg_low.priority == 0
        assert cfg_high.priority == 10000


class TestPluginsConfig:
    def test_defaults(self) -> None:
        cfg = PluginsConfig()
        assert cfg.enabled is True
        assert cfg.entries == []

    def test_with_entries(self) -> None:
        cfg = PluginsConfig(entries=[PluginConfig(name="a"), PluginConfig(name="b", enabled=False)])
        assert len(cfg.entries) == 2
        assert cfg.entries[1].enabled is False


# PluginBase


class TestPluginBase:
    async def test_default_hooks_are_noop(self) -> None:
        plugin = _NoopPlugin(_make_config())
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        assert await plugin.tool_pre_invoke(ctx) is ctx
        assert await plugin.tool_post_invoke(ctx) is ctx
        assert await plugin.prompt_pre_fetch(ctx) is ctx
        assert await plugin.resource_pre_fetch(ctx) is ctx

    async def test_name_from_config(self) -> None:
        plugin = _NoopPlugin(_make_config(name="my-plugin"))
        assert plugin.name == "my-plugin"

    async def test_lifecycle_hooks(self) -> None:
        plugin = _LifecyclePlugin(_make_config())
        assert not plugin.loaded
        await plugin.on_load()
        assert plugin.loaded
        await plugin.on_unload()
        assert plugin.unloaded


# PluginRegistry


class TestPluginRegistry:
    def test_register_and_load(self) -> None:
        register_plugin("pre-invoke-test", _PreInvokePlugin)
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="pre-invoke-test")])
        assert registry.count == 1
        assert registry.get("pre-invoke-test") is not None

    def test_disabled_plugin_skipped(self) -> None:
        register_plugin("disabled-test", _NoopPlugin)
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="disabled-test", enabled=False)])
        assert registry.count == 0

    def test_unknown_plugin_skipped(self) -> None:
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="nonexistent")])
        assert registry.count == 0

    def test_get_by_hook_returns_overriders_only(self) -> None:
        register_plugin("noop", _NoopPlugin)
        register_plugin("pre", _PreInvokePlugin)
        registry = PluginRegistry()
        registry.load_from_config(
            [
                _make_config(name="noop"),
                _make_config(name="pre"),
            ]
        )
        hooks = registry.get_by_hook("tool_pre_invoke")
        assert len(hooks) == 1
        assert hooks[0].name == "pre"

    def test_get_by_hook_priority_sort(self) -> None:
        register_plugin("high", _PreInvokePlugin)
        register_plugin("low", _PreInvokePlugin)
        registry = PluginRegistry()
        registry.load_from_config(
            [
                _make_config(name="high", priority=200),
                _make_config(name="low", priority=50),
            ]
        )
        hooks = registry.get_by_hook("tool_pre_invoke")
        assert [h.name for h in hooks] == ["low", "high"]

    async def test_load_and_unload_all(self) -> None:
        register_plugin("lc", _LifecyclePlugin)
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="lc")])
        plugin = registry.get("lc")
        assert isinstance(plugin, _LifecyclePlugin)

        await registry.load_all()
        assert plugin.loaded

        await registry.unload_all()
        assert plugin.unloaded

    def test_all_plugins_load_order(self) -> None:
        register_plugin("a", _NoopPlugin)
        register_plugin("b", _NoopPlugin)
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="a"), _make_config(name="b")])
        assert [p.name for p in registry.all_plugins()] == ["a", "b"]


# PluginManager


class TestPluginManager:
    def _make_manager(self, *plugins_and_configs: tuple[str, type, PluginConfig]) -> PluginManager:
        """Helper: register plugins, build registry + manager."""
        for name, cls, _cfg in plugins_and_configs:
            register_plugin(name, cls)
        registry = PluginRegistry()
        registry.load_from_config([cfg for _, _, cfg in plugins_and_configs])
        return PluginManager(registry)

    async def test_no_plugins_passthrough(self) -> None:
        manager = PluginManager(PluginRegistry())
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert result is ctx

    async def test_pre_invoke_mutates_metadata(self) -> None:
        cfg = _make_config(name="pre")
        manager = self._make_manager(("pre", _PreInvokePlugin, cfg))
        ctx = PluginContext(capability_name="echo", mcp_method="call_tool")
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert result.metadata["pre_touched_by"] == "pre"

    async def test_post_invoke_modifies_result(self) -> None:
        cfg = _make_config(name="post")
        manager = self._make_manager(("post", _PostInvokePlugin, cfg))
        ctx = PluginContext(capability_name="echo", mcp_method="call_tool", metadata={})
        ctx.result = "original"
        result = await manager.run_hook("tool_post_invoke", ctx)
        assert result.result == "modified:original"
        assert result.metadata["post_touched_by"] == "post"

    async def test_timeout_enforce_raises(self) -> None:
        cfg = _make_config(
            name="slow",
            timeout=0.1,
            execution_mode=ExecutionMode.enforce,
        )
        manager = self._make_manager(("slow", _SlowPlugin, cfg))
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        with pytest.raises(PluginError, match="slow"):
            await manager.run_hook("tool_pre_invoke", ctx)

    async def test_timeout_ignore_error_continues(self) -> None:
        cfg = _make_config(
            name="slow",
            timeout=0.1,
            execution_mode=ExecutionMode.enforce_ignore_error,
        )
        manager = self._make_manager(("slow", _SlowPlugin, cfg))
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        result = await manager.run_hook("tool_pre_invoke", ctx)
        # Should not raise — just continue
        assert result.capability_name == "t"

    async def test_error_enforce_raises(self) -> None:
        cfg = _make_config(
            name="err",
            execution_mode=ExecutionMode.enforce,
        )
        manager = self._make_manager(("err", _ErrorPlugin, cfg))
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        with pytest.raises(PluginError, match="intentional"):
            await manager.run_hook("tool_pre_invoke", ctx)

    async def test_error_permissive_continues(self) -> None:
        cfg = _make_config(
            name="err",
            execution_mode=ExecutionMode.permissive,
        )
        manager = self._make_manager(("err", _ErrorPlugin, cfg))
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert result.capability_name == "t"

    async def test_disabled_mode_skips(self) -> None:
        cfg = _make_config(
            name="disabled",
            execution_mode=ExecutionMode.disabled,
        )
        manager = self._make_manager(("disabled", _PreInvokePlugin, cfg))
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert "pre_touched_by" not in result.metadata

    async def test_condition_server_filter(self) -> None:
        cfg = _make_config(
            name="filtered",
            conditions=PluginCondition(servers=["backend-a"]),
        )
        manager = self._make_manager(("filtered", _PreInvokePlugin, cfg))

        ctx = PluginContext(
            capability_name="t",
            mcp_method="call_tool",
            server_name="backend-b",
        )
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert "pre_touched_by" not in result.metadata

        ctx2 = PluginContext(
            capability_name="t",
            mcp_method="call_tool",
            server_name="backend-a",
        )
        result2 = await manager.run_hook("tool_pre_invoke", ctx2)
        assert result2.metadata["pre_touched_by"] == "filtered"

    async def test_condition_tool_filter(self) -> None:
        cfg = _make_config(
            name="tool-filter",
            conditions=PluginCondition(tools=["allowed_tool"]),
        )
        manager = self._make_manager(("tool-filter", _PreInvokePlugin, cfg))

        ctx = PluginContext(capability_name="blocked_tool", mcp_method="call_tool")
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert "pre_touched_by" not in result.metadata

    async def test_condition_mcp_method_filter(self) -> None:
        cfg = _make_config(
            name="method-filter",
            conditions=PluginCondition(mcp_methods=["read_resource"]),
        )
        manager = self._make_manager(("method-filter", _PreInvokePlugin, cfg))

        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        result = await manager.run_hook(
            "tool_pre_invoke",
            ctx,
            mcp_method="call_tool",
        )
        assert "pre_touched_by" not in result.metadata

    async def test_copy_on_write_isolation(self) -> None:
        cfg = _make_config(name="mutator")
        manager = self._make_manager(("mutator", _ArgumentMutator, cfg))
        original_args = {"key": "val"}
        ctx = PluginContext(
            capability_name="t",
            mcp_method="call_tool",
            arguments=original_args,
        )
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert result.arguments["injected"] is True
        # Original dict not affected (PluginContext.__init__ copies)
        assert "injected" not in original_args

    async def test_priority_ordering(self) -> None:
        """Plugins should execute in priority order (lowest first)."""

        class _First(PluginBase):
            async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
                ctx.metadata.setdefault("order", []).append("first")
                return ctx

        class _Second(PluginBase):
            async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
                ctx.metadata.setdefault("order", []).append("second")
                return ctx

        register_plugin("first", _First)
        register_plugin("second", _Second)
        registry = PluginRegistry()
        registry.load_from_config(
            [
                _make_config(name="second", priority=200),
                _make_config(name="first", priority=50),
            ]
        )
        manager = PluginManager(registry)
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        result = await manager.run_hook("tool_pre_invoke", ctx)
        assert result.metadata["order"] == ["first", "second"]

    async def test_convenience_wrappers(self) -> None:
        manager = PluginManager(PluginRegistry())
        ctx = PluginContext(capability_name="t", mcp_method="call_tool")
        assert await manager.run_tool_pre_invoke(ctx) is ctx
        assert await manager.run_tool_post_invoke(ctx) is ctx
        assert await manager.run_prompt_pre_fetch(ctx) is ctx
        assert await manager.run_resource_pre_fetch(ctx) is ctx


# PluginMiddleware


class TestPluginMiddleware:
    async def test_call_tool_pre_and_post(self) -> None:
        """call_tool triggers both pre and post hooks."""
        cfg = _make_config(name="pre")
        register_plugin("pre", _PreInvokePlugin)
        cfg_post = _make_config(name="post")
        register_plugin("post", _PostInvokePlugin)

        registry = PluginRegistry()
        registry.load_from_config([cfg, cfg_post])
        manager = PluginManager(registry)
        mw = PluginMiddleware(manager)

        from argus_mcp.bridge.middleware.chain import RequestContext

        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")

        next_handler = AsyncMock(return_value="backend_result")
        result = await mw(ctx, next_handler)

        next_handler.assert_called_once_with(ctx)
        # Pre-hook metadata should be set
        assert ctx.metadata.get("pre_touched_by") == "pre"
        # Post-hook should have modified result
        assert result == "modified:backend_result"

    async def test_read_resource_pre_only(self) -> None:
        """read_resource triggers resource_pre_fetch but NOT tool_post_invoke."""

        class _ResourcePlugin(PluginBase):
            async def resource_pre_fetch(self, ctx: PluginContext) -> PluginContext:
                ctx.metadata["resource_checked"] = True
                return ctx

        register_plugin("res", _ResourcePlugin)
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="res")])
        manager = PluginManager(registry)
        mw = PluginMiddleware(manager)

        from argus_mcp.bridge.middleware.chain import RequestContext

        ctx = RequestContext(capability_name="data.txt", mcp_method="read_resource")
        next_handler = AsyncMock(return_value="content")
        result = await mw(ctx, next_handler)

        assert result == "content"
        assert ctx.metadata.get("resource_checked") is True

    async def test_get_prompt_pre_only(self) -> None:
        """get_prompt triggers prompt_pre_fetch only."""

        class _PromptPlugin(PluginBase):
            async def prompt_pre_fetch(self, ctx: PluginContext) -> PluginContext:
                ctx.metadata["prompt_checked"] = True
                return ctx

        register_plugin("prompt", _PromptPlugin)
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="prompt")])
        manager = PluginManager(registry)
        mw = PluginMiddleware(manager)

        from argus_mcp.bridge.middleware.chain import RequestContext

        ctx = RequestContext(capability_name="my-prompt", mcp_method="get_prompt")
        next_handler = AsyncMock(return_value="prompt_data")
        result = await mw(ctx, next_handler)

        assert result == "prompt_data"
        assert ctx.metadata.get("prompt_checked") is True

    async def test_unknown_method_passthrough(self) -> None:
        """Unknown mcp_method should just pass through without hooks."""
        register_plugin("pre", _PreInvokePlugin)
        registry = PluginRegistry()
        registry.load_from_config([_make_config(name="pre")])
        manager = PluginManager(registry)
        mw = PluginMiddleware(manager)

        from argus_mcp.bridge.middleware.chain import RequestContext

        ctx = RequestContext(capability_name="t", mcp_method="list_tools")
        next_handler = AsyncMock(return_value="tools")
        result = await mw(ctx, next_handler)

        assert result == "tools"
        assert "pre_touched_by" not in ctx.metadata


# _request_to_plugin_ctx helper


class TestRequestToPluginCtx:
    def test_conversion(self) -> None:
        from argus_mcp.bridge.middleware.chain import RequestContext

        req = RequestContext(
            capability_name="echo",
            mcp_method="call_tool",
            arguments={"a": 1},
            server_name="backend-1",
        )
        req.metadata["key"] = "val"
        pctx = _request_to_plugin_ctx(req, result="res")
        assert pctx.capability_name == "echo"
        assert pctx.mcp_method == "call_tool"
        assert pctx.arguments == {"a": 1}
        assert pctx.server_name == "backend-1"
        assert pctx.metadata == {"key": "val"}
        assert pctx.result == "res"


# Config integration — ArgusConfig.plugins


class TestArgusConfigPlugins:
    def test_default_plugins_field(self) -> None:
        from argus_mcp.config.schema import ArgusConfig

        cfg = ArgusConfig()
        assert cfg.plugins.enabled is True
        assert cfg.plugins.entries == []

    def test_plugins_from_dict(self) -> None:
        from argus_mcp.config.schema import ArgusConfig

        cfg = ArgusConfig(
            plugins={
                "enabled": True,
                "entries": [
                    {"name": "secrets_detection", "priority": 50},
                    {"name": "pii_filter", "enabled": False},
                ],
            }
        )
        assert len(cfg.plugins.entries) == 2
        assert cfg.plugins.entries[0].priority == 50
        assert cfg.plugins.entries[1].enabled is False


# ServerState — plugin_manager field


class TestServerStatePluginManager:
    def test_default_none(self) -> None:
        from argus_mcp.server.state import ServerState

        state = ServerState()
        assert state.plugin_manager is None

    def test_with_manager(self) -> None:
        from argus_mcp.server.state import ServerState

        manager = PluginManager(PluginRegistry())
        state = ServerState(plugin_manager=manager)
        assert state.plugin_manager is manager

    def test_get_state_fallback(self) -> None:
        from argus_mcp.server.state import get_state

        mock_server = type("MockServer", (), {})()
        state = get_state(mock_server)
        assert state.plugin_manager is None
