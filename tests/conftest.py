"""Shared fixtures and configuration for the Argus MCP test suite.

Provides:
- Standardised async mode (auto) for all tests
- Mock backend sessions and registries
- Config factories for deterministic testing
- Network isolation helpers
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# Semgrep authentication ──────────────────────────────────────────────
# Set the token so semgrep CLI never prompts for login during test runs.
# Safe to keep here — the tests/ folder is excluded from the remote repo
# via .git/info/exclude.
os.environ.setdefault(
    "SEMGREP_APP_TOKEN",
    "3787eeeb71d13e9af2f8baddcf5867a82b9ad37b59725dc51c03f745b484a611",
)


# pytest-asyncio configuration ────────────────────────────────────────


def pytest_configure(config: Any) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with -m 'not slow')")
    config.addinivalue_line("markers", "integration: marks integration tests")
    config.addinivalue_line("markers", "security: marks security-focused tests")
    config.addinivalue_line("markers", "semgrep: marks semgrep rule validation tests")


# Mock Backend Session ────────────────────────────────────────────────


class MockMCPSession:
    """Deterministic mock of an MCP ClientSession for testing.

    Simulates the interface of mcp.ClientSession with configurable
    responses and optional side-effects for error testing.
    """

    def __init__(
        self,
        name: str = "mock-backend",
        tools: Optional[List[Dict[str, Any]]] = None,
        resources: Optional[List[Dict[str, Any]]] = None,
        prompts: Optional[List[Dict[str, Any]]] = None,
        call_tool_response: Any = None,
        call_tool_error: Optional[Exception] = None,
        read_resource_response: Any = None,
        get_prompt_response: Any = None,
    ) -> None:
        self.name = name
        self._tools = tools or [
            {"name": "echo", "description": "Echo input", "inputSchema": {"type": "object"}},
        ]
        self._resources = resources or []
        self._prompts = prompts or []
        self._call_tool_response = call_tool_response
        self._call_tool_error = call_tool_error
        self._read_resource_response = read_resource_response
        self._get_prompt_response = get_prompt_response

    async def list_tools(self) -> Any:
        mock_result = MagicMock()
        mock_tools = []
        for t in self._tools:
            tool = MagicMock()
            tool.name = t["name"]
            tool.description = t.get("description", "")
            tool.inputSchema = t.get("inputSchema", {})
            mock_tools.append(tool)
        mock_result.tools = mock_tools
        return mock_result

    async def list_resources(self) -> Any:
        mock_result = MagicMock()
        mock_resources = []
        for r in self._resources:
            res = MagicMock()
            res.name = r.get("name", "")
            res.uri = r.get("uri", "")
            res.description = r.get("description", "")
            mock_resources.append(res)
        mock_result.resources = mock_resources
        return mock_result

    async def list_prompts(self) -> Any:
        mock_result = MagicMock()
        mock_prompts = []
        for p in self._prompts:
            prompt = MagicMock()
            prompt.name = p.get("name", "")
            prompt.description = p.get("description", "")
            mock_prompts.append(prompt)
        mock_result.prompts = mock_prompts
        return mock_result

    async def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        if self._call_tool_error:
            raise self._call_tool_error
        if self._call_tool_response is not None:
            return self._call_tool_response
        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text=f"Called {name}")]
        mock_result.isError = False
        return mock_result

    async def read_resource(self, uri: str) -> Any:
        if self._read_resource_response is not None:
            return self._read_resource_response
        mock_result = MagicMock()
        mock_result.contents = [MagicMock(text=f"Resource: {uri}")]
        return mock_result

    async def get_prompt(self, name: str, arguments: Dict[str, Any] = None) -> Any:
        if self._get_prompt_response is not None:
            return self._get_prompt_response
        mock_result = MagicMock()
        mock_result.messages = [MagicMock(content=f"Prompt: {name}")]
        return mock_result

    async def initialize(self) -> None:
        pass


@pytest.fixture
def mock_session() -> MockMCPSession:
    """A simple mock MCP session with one tool."""
    return MockMCPSession()


@pytest.fixture
def mock_session_factory():
    """Factory fixture for creating mock sessions with custom config."""

    def _create(**kwargs: Any) -> MockMCPSession:
        return MockMCPSession(**kwargs)

    return _create


# Mock Capability Registry ────────────────────────────────────────────


@pytest.fixture
def mock_registry():
    """A MagicMock registry with basic resolve_capability behaviour."""
    registry = MagicMock()
    registry._tools = []
    registry._resources = []
    registry._prompts = []
    registry._route_map = {}

    def resolve(name: str):
        return registry._route_map.get(name)

    registry.resolve_capability = MagicMock(side_effect=resolve)
    return registry


@pytest.fixture
def mock_manager():
    """A MagicMock client manager with basic get_session behaviour."""
    manager = MagicMock()
    manager._sessions = {}

    def get_session(name: str):
        return manager._sessions.get(name)

    def get_all_sessions():
        return dict(manager._sessions)

    manager.get_session = MagicMock(side_effect=get_session)
    manager.get_all_sessions = MagicMock(side_effect=get_all_sessions)
    manager.get_status_record = MagicMock(return_value=None)
    return manager


# Config Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def minimal_config() -> Dict[str, Any]:
    """Minimal valid Argus configuration dict."""
    return {
        "version": "1",
        "mcpServers": {
            "test-server": {
                "type": "stdio",
                "params": {
                    "command": "echo",
                    "args": ["hello"],
                },
            },
        },
    }


@pytest.fixture
def multi_backend_config() -> Dict[str, Any]:
    """Configuration with multiple backends for conflict/registry testing."""
    return {
        "version": "1",
        "mcpServers": {
            "server-a": {
                "type": "stdio",
                "params": {"command": "echo", "args": ["a"]},
            },
            "server-b": {
                "type": "stdio",
                "params": {"command": "echo", "args": ["b"]},
            },
            "server-c": {
                "type": "sse",
                "url": "http://localhost:9999/sse",
            },
        },
    }
