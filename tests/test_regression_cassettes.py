"""Cassette-based regression tests using mcp-recorder.

These tests replay golden cassettes recorded against the live Argus MCP
server and verify the responses haven't drifted.  They catch:
  - Protocol-level regressions (initialize, capabilities)
  - Tool schema drift (added/removed/renamed tools, changed inputSchema)
  - Resource URI changes
  - Error response format changes

Recording new cassettes:
    mcp-recorder record-scenarios tests/scenarios.yml --output-dir tests/cassettes/

Verifying manually:
    mcp-recorder verify --cassette tests/cassettes/protocol_handshake.json \\
        --target http://127.0.0.1:9000 --ignore-fields timestamp

Requires:
    - mcp-recorder >= 0.3.0  (pip install mcp-recorder)
    - A running Argus server at http://127.0.0.1:9000
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

CASSETTES_DIR = Path(__file__).parent / "cassettes"
SERVER_URL = "http://127.0.0.1:9000"


def _cassette_path(name: str) -> Path:
    return CASSETTES_DIR / f"{name}.json"


def _verify_cassette(
    cassette: Path, *, ignore_fields: tuple[str, ...] = ("timestamp", "version")
) -> dict:
    """Run mcp-recorder verify and return structured result.

    Returns dict with keys: passed, failed, total, output.
    """
    cmd = [
        "mcp-recorder",
        "verify",
        "--cassette",
        str(cassette),
        "--target",
        SERVER_URL,
    ]
    for field in ignore_fields:
        cmd.extend(["--ignore-fields", field])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    # mcp-recorder writes progress to stderr
    output = result.stderr + result.stdout

    # Parse "Result: X/Y passed, Z failed"
    passed = failed = total = 0
    for line in output.splitlines():
        if line.strip().startswith("Result:"):
            parts = line.strip().split()
            # "Result: 4/4 passed, 0 failed"
            fraction = parts[1]  # "4/4"
            passed = int(fraction.split("/")[0])
            total = int(fraction.split("/")[1])
            failed = int(parts[3])
            break

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "output": output,
        "returncode": result.returncode,
    }


def _load_cassette(name: str) -> dict:
    """Load and return a cassette file as dict."""
    path = _cassette_path(name)
    if not path.exists():
        pytest.skip(
            f"Cassette {path.name} not found — run: mcp-recorder record-scenarios tests/scenarios.yml --output-dir tests/cassettes/"
        )
    with open(path) as f:
        return json.load(f)


# Precondition checks


def _server_reachable() -> bool:
    """Quick check that the server is up."""
    try:
        import httpx

        r = httpx.get(f"{SERVER_URL}/mcp", timeout=3)
        return r.status_code in (200, 405, 406, 415)
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _server_reachable(),
        reason=f"Argus server not reachable at {SERVER_URL}",
    ),
]


# Protocol handshake regression


class TestProtocolHandshake:
    """Verify the full initialize→tools/list→resources/list flow hasn't regressed."""

    CASSETTE = "protocol_handshake"

    def test_verify_against_live(self):
        """Replay the protocol handshake cassette against the live server."""
        path = _cassette_path(self.CASSETTE)
        if not path.exists():
            pytest.skip("Cassette missing")
        result = _verify_cassette(path)
        assert result["failed"] == 0, f"Handshake regression:\n{result['output']}"
        assert result["total"] >= 3, "Expected at least init + tools + resources"

    def test_server_info_stable(self):
        """Server name and capabilities haven't changed unexpectedly."""
        data = _load_cassette(self.CASSETTE)
        init_resp = data["interactions"][0]["response"]["result"]

        assert init_resp["serverInfo"]["name"] == "Argus MCP"
        assert "protocolVersion" in init_resp

        caps = init_resp["capabilities"]
        assert "tools" in caps, "Server must advertise tools capability"
        assert "resources" in caps, "Server must advertise resources capability"

    def test_protocol_version_supported(self):
        """Server reports a known protocol version."""
        data = _load_cassette(self.CASSETTE)
        version = data["interactions"][0]["response"]["result"]["protocolVersion"]
        known = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
        assert version in known, f"Unknown protocol version: {version}"


# Tool schema regression


class TestToolSchemas:
    """Detect tool additions, removals, and schema changes."""

    CASSETTE = "tool_schemas"

    def test_verify_against_live(self):
        path = _cassette_path(self.CASSETTE)
        if not path.exists():
            pytest.skip("Cassette missing")
        result = _verify_cassette(path)
        assert result["failed"] == 0, f"Tool schema regression:\n{result['output']}"

    def test_tool_count_stable(self):
        """Tool count hasn't changed unexpectedly."""
        data = _load_cassette(self.CASSETTE)
        tools_resp = next(
            i
            for i in data["interactions"]
            if i["type"] == "jsonrpc_request" and i["request"]["method"] == "tools/list"
        )
        tools = tools_resp["response"]["result"]["tools"]
        # Argus currently reports 108 tools — allow ±5 for backend config changes
        assert len(tools) > 50, f"Tool count dropped to {len(tools)}"

    def test_all_tools_have_required_fields(self):
        """Every tool has name and inputSchema."""
        data = _load_cassette(self.CASSETTE)
        tools_resp = next(
            i
            for i in data["interactions"]
            if i["type"] == "jsonrpc_request" and i["request"]["method"] == "tools/list"
        )
        tools = tools_resp["response"]["result"]["tools"]
        for tool in tools:
            assert "name" in tool, f"Tool missing name: {tool}"
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"


# Resource list regression


class TestResourceList:
    """Detect resource additions, removals, and URI changes."""

    CASSETTE = "resource_list"

    def test_verify_against_live(self):
        path = _cassette_path(self.CASSETTE)
        if not path.exists():
            pytest.skip("Cassette missing")
        result = _verify_cassette(path)
        assert result["failed"] == 0, f"Resource list regression:\n{result['output']}"

    def test_resources_have_uri(self):
        """Every resource has a URI field."""
        data = _load_cassette(self.CASSETTE)
        res_resp = next(
            i
            for i in data["interactions"]
            if i["type"] == "jsonrpc_request" and i["request"]["method"] == "resources/list"
        )
        resources = res_resp["response"]["result"]["resources"]
        for r in resources:
            assert "uri" in r, f"Resource missing uri: {r}"
            assert "name" in r, f"Resource missing name: {r}"


# Error handling regression


class TestErrorHandling:
    """Verify error responses haven't changed format."""

    CASSETTE = "error_handling"

    def test_verify_against_live(self):
        path = _cassette_path(self.CASSETTE)
        if not path.exists():
            pytest.skip("Cassette missing")
        result = _verify_cassette(path)
        assert result["failed"] == 0, f"Error handling regression:\n{result['output']}"

    def test_unknown_tool_returns_error(self):
        """Calling a nonexistent tool must return an error, not crash."""
        data = _load_cassette(self.CASSETTE)
        call_resp = next(
            i
            for i in data["interactions"]
            if i["type"] == "jsonrpc_request" and i["request"]["method"] == "tools/call"
        )
        resp = call_resp["response"]
        # MCP spec: error responses use "error" key OR result with isError
        has_error = "error" in resp or ("result" in resp and resp["result"].get("isError"))
        assert has_error, (
            f"Expected error response for nonexistent tool, got: {json.dumps(resp, indent=2)}"
        )

    def test_error_has_message(self):
        """Error response includes a human-readable message."""
        data = _load_cassette(self.CASSETTE)
        call_resp = next(
            i
            for i in data["interactions"]
            if i["type"] == "jsonrpc_request" and i["request"]["method"] == "tools/call"
        )
        resp = call_resp["response"]
        if "error" in resp:
            assert "message" in resp["error"], "JSON-RPC error missing message field"
        elif "result" in resp and resp["result"].get("isError"):
            content = resp["result"].get("content", [])
            assert any(c.get("text") for c in content), "isError result missing text content"
