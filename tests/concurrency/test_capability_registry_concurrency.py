"""Concurrency stress tests for CapabilityRegistry (CONC-02 validation).

Each test runs 50x via pytest-repeat to surface non-deterministic races.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from argus_mcp.bridge.capability_registry import CapabilityRegistry

try:
    from mcp import types as mcp_types
except ImportError:
    mcp_types = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_tool(name: str, description: str = "tool") -> MagicMock:
    tool = MagicMock(spec=mcp_types.Tool)
    tool.name = name
    tool.description = description
    tool.inputSchema = {"type": "object"}
    tool.model_copy = MagicMock(return_value=tool)
    return tool


def _make_session(
    tools: list | None = None,
    resources: list | None = None,
    prompts: list | None = None,
) -> AsyncMock:
    session = AsyncMock(name="ClientSession")

    tools_resp = MagicMock()
    tools_resp.tools = tools or []
    session.list_tools = AsyncMock(return_value=tools_resp)

    res_resp = MagicMock()
    res_resp.resources = resources or []
    session.list_resources = AsyncMock(return_value=res_resp)

    prompts_resp = MagicMock()
    prompts_resp.prompts = prompts or []
    session.list_prompts = AsyncMock(return_value=prompts_resp)

    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.repeat(50)
async def test_snapshot_swap_readers_see_consistent_state():
    """Readers calling get_aggregated_tools during discover never see partial lists.

    The snapshot-and-swap pattern guarantees that self._tools is replaced
    atomically under the lock.  Readers should see either 0 (pre-discover)
    or 10 (post-discover) tools -- never a partial count like 1 or 2.
    """
    registry = CapabilityRegistry(
        conflict_strategy=None,
        filters=None,
        rename_maps=None,
        cap_fetch_timeouts=None,
    )

    sessions: dict[str, AsyncMock] = {}
    for i in range(5):
        sessions[f"backend-{i}"] = _make_session(
            tools=[_mock_tool(f"tool-{i}-a"), _mock_tool(f"tool-{i}-b")],
        )

    valid_counts = {0, 10}  # pre-discover or post-discover
    invalid_seen: list[int] = []

    async def _reader() -> None:
        for _ in range(20):
            tools = registry.get_aggregated_tools()
            if len(tools) not in valid_counts:
                invalid_seen.append(len(tools))
            await asyncio.sleep(0)

    async def _writer() -> None:
        await registry.discover_and_register(sessions)

    readers = [asyncio.create_task(_reader()) for _ in range(10)]
    writer = asyncio.create_task(_writer())
    await asyncio.gather(writer, *readers)

    assert invalid_seen == [], f"Readers saw partial tool counts: {invalid_seen}"
    # After writer completes, final state must have all 10 tools
    assert len(registry.get_aggregated_tools()) == 10


@pytest.mark.repeat(50)
async def test_rediscovery_replaces_state_completely():
    """Re-calling discover_and_register with new sessions fully replaces old state.

    This validates the snapshot-and-swap: the second call must not leave
    stale tools from the first call.  Concurrent readers during the second
    discover should see either 10 (old) or 6 (new), never a mix.
    """
    registry = CapabilityRegistry(
        conflict_strategy=None,
        filters=None,
        rename_maps=None,
        cap_fetch_timeouts=None,
    )

    # First discovery: 5 backends x 2 tools = 10 tools
    sessions_v1: dict[str, AsyncMock] = {}
    for i in range(5):
        sessions_v1[f"backend-{i}"] = _make_session(
            tools=[_mock_tool(f"tool-{i}-a"), _mock_tool(f"tool-{i}-b")],
        )
    await registry.discover_and_register(sessions_v1)
    assert len(registry.get_aggregated_tools()) == 10

    # Second discovery: 3 backends x 2 tools = 6 tools (different backends)
    sessions_v2: dict[str, AsyncMock] = {}
    for i in range(3):
        sessions_v2[f"new-backend-{i}"] = _make_session(
            tools=[_mock_tool(f"new-tool-{i}-a"), _mock_tool(f"new-tool-{i}-b")],
        )

    valid_counts = {10, 6}  # old state or new state
    invalid_seen: list[int] = []

    async def _reader() -> None:
        for _ in range(20):
            tools = registry.get_aggregated_tools()
            if len(tools) not in valid_counts:
                invalid_seen.append(len(tools))
            await asyncio.sleep(0)

    async def _writer() -> None:
        await registry.discover_and_register(sessions_v2)

    readers = [asyncio.create_task(_reader()) for _ in range(10)]
    writer = asyncio.create_task(_writer())
    await asyncio.gather(writer, *readers)

    assert invalid_seen == [], f"Readers saw unexpected tool counts: {invalid_seen}"
    # After second discover, state must be fully replaced
    tools = registry.get_aggregated_tools()
    assert len(tools) == 6
    tool_names = {t.name for t in tools}
    for i in range(3):
        assert f"new-tool-{i}-a" in tool_names
        assert f"new-tool-{i}-b" in tool_names
