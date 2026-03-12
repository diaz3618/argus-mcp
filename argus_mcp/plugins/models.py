"""Pydantic configuration models for the plugin framework."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    """How plugin errors affect request processing.

    - ``enforce``: Plugin error fails the request.
    - ``enforce_ignore_error``: Plugin error is logged but request continues.
    - ``permissive``: Like enforce_ignore_error with relaxed validation.
    - ``disabled``: Hook is skipped entirely.
    """

    enforce = "enforce"
    enforce_ignore_error = "enforce_ignore_error"
    permissive = "permissive"
    disabled = "disabled"


class PluginCondition(BaseModel):
    """Condition filters for when a plugin hook should fire.

    If a list is empty the condition is unrestricted (matches all).
    """

    servers: List[str] = Field(
        default_factory=list,
        description="Backend server names this plugin applies to (empty = all).",
    )
    tools: List[str] = Field(
        default_factory=list,
        description="Tool/capability names this plugin applies to (empty = all).",
    )
    mcp_methods: List[str] = Field(
        default_factory=list,
        description="MCP methods (call_tool, read_resource, get_prompt) to filter on.",
    )


class PluginConfig(BaseModel):
    """Configuration for a single plugin instance."""

    name: str = Field(description="Unique plugin identifier.")
    enabled: bool = Field(default=True, description="Whether the plugin is active.")
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.enforce_ignore_error,
        description="How plugin errors affect request processing.",
    )
    priority: int = Field(
        default=100,
        ge=0,
        le=10000,
        description="Execution priority (lower = runs first).",
    )
    timeout: float = Field(
        default=30.0,
        ge=0.1,
        le=300.0,
        description="Per-hook timeout in seconds.",
    )
    conditions: PluginCondition = Field(
        default_factory=PluginCondition,
        description="Conditions controlling when plugin hooks fire.",
    )
    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Plugin-specific key-value settings.",
    )


class PluginsConfig(BaseModel):
    """Top-level plugins section in ``config.yaml``.

    Example YAML::

        plugins:
          enabled: true
          entries:
            - name: secrets_detection
              enabled: true
              execution_mode: enforce
              priority: 10
            - name: pii_filter
              priority: 20
    """

    enabled: bool = Field(default=True, description="Global plugin system toggle.")
    entries: List[PluginConfig] = Field(
        default_factory=list,
        description="Ordered list of plugin configurations.",
    )
