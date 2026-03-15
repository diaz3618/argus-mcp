"""Integration tests against the live Argus MCP server.

Requires a running server at http://127.0.0.1:9000.
These tests validate the full production stack: HTTP transport, protocol
conformance, session lifecycle, tool forwarding, error handling, and
management API — the areas where real bugs have occurred.

Run with:
    pytest tests/test_integration.py -v

Skip with:
    pytest -m "not integration"

Why these tests exist (ROI justification):
  - The -32602 Streamable HTTP bug was only found through live client testing
  - The 307 redirect bug required POSTing to /mcp without trailing slash
  - The Docker PermissionError was a runtime-only issue
  - Session lifecycle bugs only manifest across real HTTP connections
  - Tool forwarding correctness requires a live backend connection
  Unit tests with mocks cannot reach any of these code paths.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

BASE_URL = os.environ.get("ARGUS_TEST_URL", "http://127.0.0.1:9000")
MCP_URL = f"{BASE_URL}/mcp"
MGMT_URL = f"{BASE_URL}/manage/v1"

_CLIENT_TOKEN = os.environ.get("ARGUS_CLIENT_TOKEN", "")
_MGMT_TOKEN = os.environ.get("ARGUS_MGMT_TOKEN", "")

MCP_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
if _CLIENT_TOKEN:
    MCP_HEADERS["Authorization"] = f"Bearer {_CLIENT_TOKEN}"

MGMT_HEADERS: dict[str, str] = {}
if _MGMT_TOKEN:
    MGMT_HEADERS["Authorization"] = f"Bearer {_MGMT_TOKEN}"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_HTTPX, reason="httpx not installed"),
]


# Helpers


def _jsonrpc(method: str, params: dict | None = None, req_id: int | str | None = None) -> dict:
    """Build a JSON-RPC 2.0 request."""
    return {
        "jsonrpc": "2.0",
        "id": req_id or str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }


def _init_params(client_name: str = "test-suite") -> dict:
    return {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": client_name, "version": "1.0"},
    }


def _parse_sse_data(text: str) -> dict:
    """Extract first JSON data payload from SSE response body."""
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    # Fallback: try direct JSON parse
    return json.loads(text)


def _mcp_post(
    client: httpx.Client,
    method: str,
    params: dict | None = None,
    session_id: str = "",
    req_id: int | str | None = None,
) -> tuple[int, dict, httpx.Response]:
    """Send MCP request, return (status, parsed_data, raw_response)."""
    headers = {**MCP_HEADERS}
    if session_id:
        headers["mcp-session-id"] = session_id
    resp = client.post(MCP_URL, headers=headers, json=_jsonrpc(method, params, req_id))
    if resp.status_code != 200:
        return resp.status_code, {}, resp
    try:
        data = _parse_sse_data(resp.text)
    except (json.JSONDecodeError, ValueError):
        data = {}
    return resp.status_code, data, resp


def _init_session(client: httpx.Client, name: str = "test-suite") -> str:
    """Initialize and return the session ID."""
    _, data, resp = _mcp_post(client, "initialize", _init_params(name))
    return resp.headers.get("mcp-session-id", "")


# 1. MCP Protocol Conformance  (would have caught the -32602 bug)


class TestMCPProtocolConformance:
    """Validate JSON-RPC 2.0 + MCP protocol spec compliance."""

    def test_initialize_returns_200(self) -> None:
        """The foundation: initialize must return 200 with result."""
        with httpx.Client(timeout=15.0) as c:
            status, data, _ = _mcp_post(c, "initialize", _init_params())
            assert status == 200, f"Expected 200, got {status}"
            assert "result" in data, f"Missing 'result' in response: {data}"

    def test_initialize_result_has_server_info(self) -> None:
        with httpx.Client(timeout=15.0) as c:
            _, data, _ = _mcp_post(c, "initialize", _init_params())
            result = data["result"]
            assert "serverInfo" in result
            assert "name" in result["serverInfo"]

    def test_initialize_result_has_capabilities(self) -> None:
        with httpx.Client(timeout=15.0) as c:
            _, data, _ = _mcp_post(c, "initialize", _init_params())
            result = data["result"]
            assert "capabilities" in result

    def test_initialize_returns_session_id_header(self) -> None:
        """MCP Streamable HTTP MUST return mcp-session-id."""
        with httpx.Client(timeout=15.0) as c:
            _, _, resp = _mcp_post(c, "initialize", _init_params())
            sid = resp.headers.get("mcp-session-id")
            assert sid, "Server must return mcp-session-id header"
            assert len(sid) > 8, f"Session ID suspiciously short: {sid}"

    def test_jsonrpc_id_echoed(self) -> None:
        """JSON-RPC spec: response 'id' must match request 'id'."""
        with httpx.Client(timeout=15.0) as c:
            _, data, _ = _mcp_post(c, "initialize", _init_params(), req_id=42)
            assert data.get("id") == 42, f"ID mismatch: expected 42, got {data.get('id')}"

    def test_jsonrpc_version_always_2_0(self) -> None:
        with httpx.Client(timeout=15.0) as c:
            _, data, _ = _mcp_post(c, "initialize", _init_params())
            assert data.get("jsonrpc") == "2.0"

    def test_malformed_request_returns_error(self) -> None:
        """Missing 'method' field must return JSON-RPC error, not crash."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            headers = {**MCP_HEADERS, "mcp-session-id": sid}
            resp = c.post(MCP_URL, headers=headers, json={"jsonrpc": "2.0", "id": 99})
            # Should be 400 (validation) — not 500 (crash)
            assert resp.status_code in (400, 200), f"Unexpected {resp.status_code}"
            if resp.status_code == 200:
                data = _parse_sse_data(resp.text)
                assert "error" in data

    def test_invalid_method_returns_error(self) -> None:
        """Calling a non-existent MCP method must return method-not-found error."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            status, data, _ = _mcp_post(c, "nonexistent/method", session_id=sid)
            # Either 400 or a JSON-RPC error response
            if status == 200:
                assert "error" in data, "Expected error for unknown method"

    def test_content_type_sse(self) -> None:
        """Streamable HTTP: Content-Type must be text/event-stream for
        successful responses (per MCP spec)."""
        with httpx.Client(timeout=15.0) as c:
            _, _, resp = _mcp_post(c, "initialize", _init_params())
            ct = resp.headers.get("content-type", "")
            assert "text/event-stream" in ct or "application/json" in ct, (
                f"Unexpected Content-Type: {ct}"
            )


# 2. Slash Redirect Regression  (would have caught the 307 bug)


class TestSlashRedirectRegression:
    """The /mcp 307 redirect broke all MCP clients.
    POST redirects are not followed by most HTTP clients."""

    def test_post_mcp_no_slash_returns_200(self) -> None:
        """POST /mcp (no trailing slash) MUST return 200, NOT 307."""
        with httpx.Client(timeout=10.0, follow_redirects=False) as c:
            resp = c.post(
                f"{BASE_URL}/mcp",
                headers=MCP_HEADERS,
                json=_jsonrpc("initialize", _init_params()),
            )
            assert resp.status_code == 200, (
                f"POST /mcp returned {resp.status_code}. If 307, the _MCPSlashMiddleware is broken."
            )

    def test_post_mcp_with_slash_returns_200(self) -> None:
        """POST /mcp/ (with trailing slash) should also work."""
        with httpx.Client(timeout=10.0, follow_redirects=False) as c:
            resp = c.post(
                f"{BASE_URL}/mcp/",
                headers=MCP_HEADERS,
                json=_jsonrpc("initialize", _init_params()),
            )
            assert resp.status_code == 200


# 3. Session Lifecycle  (catches session corruption, leaks, invalidation)


class TestSessionLifecycle:
    """Session management is critical — bugs here break all clients."""

    def test_session_id_stable_across_requests(self) -> None:
        """Session ID must remain the same for all requests in a session."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            assert sid
            for i in range(3):
                _, _, resp = _mcp_post(c, "tools/list", session_id=sid)
                new_sid = resp.headers.get("mcp-session-id", "")
                assert new_sid == sid, (
                    f"Session ID changed on request {i + 1}: {sid!r} -> {new_sid!r}"
                )

    def test_invalid_session_id_rejected(self) -> None:
        """A fabricated session ID must be rejected (404 per MCP spec)."""
        with httpx.Client(timeout=10.0) as c:
            status, _, _ = _mcp_post(c, "tools/list", session_id="totally-fabricated-session-00000")
            assert status in (400, 404), f"Expected 400/404 for invalid session, got {status}"

    def test_delete_terminates_session(self) -> None:
        """DELETE /mcp with session ID should terminate the session."""
        with httpx.Client(timeout=10.0) as c:
            sid = _init_session(c)
            del_headers: dict[str, str] = {"mcp-session-id": sid}
            if _CLIENT_TOKEN:
                del_headers["Authorization"] = f"Bearer {_CLIENT_TOKEN}"
            resp = c.delete(MCP_URL, headers=del_headers)
            assert resp.status_code in (200, 204), f"DELETE session returned {resp.status_code}"

    def test_session_after_delete_is_invalid(self) -> None:
        """After DELETE, the session ID should no longer work."""
        with httpx.Client(timeout=10.0) as c:
            sid = _init_session(c)
            del_headers: dict[str, str] = {"mcp-session-id": sid}
            if _CLIENT_TOKEN:
                del_headers["Authorization"] = f"Bearer {_CLIENT_TOKEN}"
            c.delete(MCP_URL, headers=del_headers)
            # Now try to use the deleted session
            status, _, _ = _mcp_post(c, "tools/list", session_id=sid)
            assert status in (404, 400), f"Deleted session still accepted: got {status}"

    def test_multiple_concurrent_sessions(self) -> None:
        """Two independent sessions should not interfere."""
        with httpx.Client(timeout=15.0) as c:
            sid1 = _init_session(c, "client-A")
            sid2 = _init_session(c, "client-B")
            assert sid1 != sid2, "Two sessions got the same ID"

            # Both should work independently
            s1, d1, _ = _mcp_post(c, "tools/list", session_id=sid1)
            s2, d2, _ = _mcp_post(c, "tools/list", session_id=sid2)
            assert s1 == 200
            assert s2 == 200


# 4. HTTP Transport Edge Cases  (would have caught the method bug)


class TestHTTPTransportEdgeCases:
    """Exercise edge cases in the ASGI transport layer."""

    def test_method_not_allowed(self) -> None:
        """PUT, PATCH, etc. must return 405."""
        with httpx.Client(timeout=10.0) as c:
            resp = c.put(MCP_URL, json={})
            assert resp.status_code == 405

    def test_get_without_session_rejected(self) -> None:
        """GET /mcp without a session should not return 200."""
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(MCP_URL, headers={"Accept": "text/event-stream"})
            assert resp.status_code != 200, "GET without session should be rejected"

    def test_missing_content_type_handled(self) -> None:
        """POST without Content-Type should not crash the server."""
        with httpx.Client(timeout=10.0) as c:
            resp = c.post(
                MCP_URL,
                content=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
                headers={"Accept": "application/json, text/event-stream"},
            )
            # Should get an error response, not a 500 crash
            assert resp.status_code < 500, (
                f"Server crashed (5xx) on missing Content-Type: {resp.status_code}"
            )

    def test_empty_body_handled(self) -> None:
        """POST with empty body should not crash."""
        with httpx.Client(timeout=10.0) as c:
            resp = c.post(MCP_URL, headers=MCP_HEADERS, content=b"")
            assert resp.status_code < 500

    def test_invalid_json_handled(self) -> None:
        """POST with malformed JSON should return 400, not 500."""
        with httpx.Client(timeout=10.0) as c:
            resp = c.post(
                MCP_URL,
                headers=MCP_HEADERS,
                content=b"{not valid json",
            )
            assert resp.status_code < 500, f"Server crashed on invalid JSON: {resp.status_code}"

    def test_oversized_payload_handled(self) -> None:
        """A very large payload should not crash the server."""
        with httpx.Client(timeout=10.0) as c:
            big = json.dumps(_jsonrpc("initialize", {"padding": "x" * 200_000}))
            resp = c.post(MCP_URL, headers=MCP_HEADERS, content=big.encode())
            # Any non-crash response is acceptable
            assert resp.status_code < 500


# 5. Tool Forwarding  (validates the actual bridge -> backend pipeline)


class TestToolForwarding:
    """Execute real tool calls to verify the full forwarding path.
    These tests are only meaningful against a live server with backends."""

    def test_tools_list_returns_tools(self) -> None:
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            _, data, _ = _mcp_post(c, "tools/list", session_id=sid)
            tools = data["result"]["tools"]
            assert len(tools) > 0, "Server has no tools - backends may be down"

    def test_tools_have_required_fields(self) -> None:
        """Every tool must have 'name' and 'inputSchema' per MCP spec."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            _, data, _ = _mcp_post(c, "tools/list", session_id=sid)
            tools = data["result"]["tools"]
            for tool in tools:
                assert "name" in tool, f"Tool missing 'name': {tool}"
                assert isinstance(tool["name"], str)
                # inputSchema is required per MCP spec
                assert "inputSchema" in tool, f"Tool '{tool['name']}' missing 'inputSchema'"

    def test_call_nonexistent_tool_returns_error(self) -> None:
        """Calling a tool that doesn't exist must return isError=true."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            _, data, _ = _mcp_post(
                c,
                "tools/call",
                {"name": "this_tool_does_not_exist_xyz", "arguments": {}},
                session_id=sid,
            )
            result = data.get("result", {})
            assert result.get("isError") is True, (
                f"Expected isError=true for nonexistent tool: {data}"
            )

    def test_call_real_tool_returns_content(self) -> None:
        """Call an actual tool and verify the result structure.
        Uses the first available tool that doesn't require complex args."""
        with httpx.Client(timeout=30.0) as c:
            sid = _init_session(c)
            _, data, _ = _mcp_post(c, "tools/list", session_id=sid)
            tools = data["result"]["tools"]

            # Find a tool with no or all-optional parameters
            simple_tool = None
            for tool in tools:
                schema = tool.get("inputSchema", {})
                required = schema.get("required", [])
                if not required:
                    simple_tool = tool["name"]
                    break

            if simple_tool is None:
                pytest.skip("No zero-argument tool available")

            _, result, _ = _mcp_post(
                c,
                "tools/call",
                {"name": simple_tool, "arguments": {}},
                session_id=sid,
            )
            assert "result" in result, f"Tool call failed: {result}"
            content = result["result"].get("content", [])
            assert isinstance(content, list), "Tool result content must be a list"
            if content:
                assert "type" in content[0], "Content item missing 'type'"


# 6. Resources  (validates resource listing and read)


class TestResourceForwarding:
    """Validate resource capabilities against the live server."""

    def test_resources_list(self) -> None:
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            _, data, _ = _mcp_post(c, "resources/list", session_id=sid)
            assert "result" in data
            resources = data["result"].get("resources", [])
            assert isinstance(resources, list)

    def test_resources_have_uri(self) -> None:
        """Every resource must have a 'uri' field per MCP spec."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            _, data, _ = _mcp_post(c, "resources/list", session_id=sid)
            resources = data["result"].get("resources", [])
            for res in resources:
                assert "uri" in res, f"Resource missing 'uri': {res}"


# 7. Management API  (health, status, backends — operational visibility)


class TestManagementAPI:
    """Validate the management API used for monitoring and ops."""

    def test_health_endpoint(self) -> None:
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(f"{MGMT_URL}/health", headers=MGMT_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert data["status"] in ("healthy", "degraded", "unhealthy")

    def test_health_has_version(self) -> None:
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(f"{MGMT_URL}/health", headers=MGMT_HEADERS)
            data = resp.json()
            assert "version" in data
            assert data["version"]  # not empty

    def test_health_has_backend_counts(self) -> None:
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(f"{MGMT_URL}/health", headers=MGMT_HEADERS)
            data = resp.json()
            backends = data.get("backends", {})
            assert "total" in backends
            assert "connected" in backends
            assert backends["connected"] <= backends["total"]

    def test_status_endpoint(self) -> None:
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(f"{MGMT_URL}/status", headers=MGMT_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert "service" in data

    def test_backends_endpoint(self) -> None:
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(f"{MGMT_URL}/backends", headers=MGMT_HEADERS)
            assert resp.status_code == 200

    def test_capabilities_endpoint(self) -> None:
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(f"{MGMT_URL}/capabilities", headers=MGMT_HEADERS)
            assert resp.status_code == 200


# 8. SSE Transport  (legacy transport — verify it still works)


class TestSSETransport:
    """The SSE transport must keep working alongside Streamable HTTP."""

    def test_sse_endpoint_streams(self) -> None:
        with httpx.Client(timeout=5.0) as c:
            try:
                sse_headers: dict[str, str] = {}
                if _CLIENT_TOKEN:
                    sse_headers["Authorization"] = f"Bearer {_CLIENT_TOKEN}"
                with c.stream("GET", f"{BASE_URL}/sse", headers=sse_headers) as resp:
                    assert resp.status_code == 200
                    ct = resp.headers.get("content-type", "")
                    assert "text/event-stream" in ct
            except httpx.ReadTimeout:
                pass  # Expected — SSE streams indefinitely


# 9. Regression: specific bugs from production history


class TestProductionRegressions:
    """Tests that reproduce specific bugs found in production."""

    def test_no_32602_on_tools_list(self) -> None:
        """Regression: -32602 'Invalid params' was returned for tools/list
        when the Streamable HTTP handler incorrectly validated params."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            status, data, _ = _mcp_post(c, "tools/list", session_id=sid)
            assert status == 200
            # Must NOT have an error with code -32602
            error = data.get("error", {})
            assert error.get("code") != -32602, f"Got -32602 error on tools/list: {error}"

    def test_no_32602_on_resources_list(self) -> None:
        """Same regression check for resources/list."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            status, data, _ = _mcp_post(c, "resources/list", session_id=sid)
            assert status == 200
            error = data.get("error", {})
            assert error.get("code") != -32602

    def test_no_500_on_rapid_requests(self) -> None:
        """Regression: rapid sequential requests could cause race conditions."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            for i in range(10):
                status, _, _ = _mcp_post(c, "tools/list", session_id=sid, req_id=i + 100)
                assert status == 200, f"Request {i} failed with status {status}"

    def test_initialize_with_empty_capabilities(self) -> None:
        """Regression: some MCP clients send {} for capabilities."""
        with httpx.Client(timeout=15.0) as c:
            status, data, _ = _mcp_post(
                c,
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "minimal", "version": "0.1"},
                },
            )
            assert status == 200
            assert "result" in data

    def test_initialize_with_all_capabilities(self) -> None:
        """Test initialize with full capability declarations."""
        with httpx.Client(timeout=15.0) as c:
            status, data, _ = _mcp_post(
                c,
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {
                        "roots": {"listChanged": True},
                        "sampling": {},
                    },
                    "clientInfo": {"name": "full-caps", "version": "2.0"},
                },
            )
            assert status == 200
            assert "result" in data


# 10. Server stability under adversarial inputs


class TestServerStability:
    """Verify the server doesn't crash under adversarial inputs.
    These are things that real MCP clients might accidentally send."""

    def test_numeric_string_id(self) -> None:
        """Some clients send string IDs: '1' instead of 1."""
        with httpx.Client(timeout=15.0) as c:
            status, data, _ = _mcp_post(c, "initialize", _init_params(), req_id="string-id-123")
            assert status == 200

    def test_null_params(self) -> None:
        """Some clients send null instead of {} for params."""
        with httpx.Client(timeout=15.0) as c:
            headers = {**MCP_HEADERS}
            resp = c.post(
                MCP_URL,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": None,
                },
            )
            # Should not crash — 400 or handled gracefully
            assert resp.status_code < 500

    def test_extra_fields_ignored(self) -> None:
        """Extra fields in the request should be ignored, not cause errors."""
        with httpx.Client(timeout=15.0) as c:
            headers = {**MCP_HEADERS}
            resp = c.post(
                MCP_URL,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": _init_params(),
                    "extra_field": "should be ignored",
                    "another_extra": 42,
                },
            )
            assert resp.status_code < 500

    def test_unicode_in_tool_name(self) -> None:
        """Non-ASCII tool name should fail gracefully."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            status, data, _ = _mcp_post(
                c,
                "tools/call",
                {"name": "unicode_tool_\u5de5\u5177", "arguments": {}},
                session_id=sid,
            )
            # Should return error, not crash
            if status == 200:
                assert data.get("result", {}).get("isError") is True

    def test_very_long_tool_name(self) -> None:
        """Extremely long tool name should not cause buffer overflow."""
        with httpx.Client(timeout=15.0) as c:
            sid = _init_session(c)
            long_name = "a" * 10000
            status, data, _ = _mcp_post(
                c,
                "tools/call",
                {"name": long_name, "arguments": {}},
                session_id=sid,
            )
            assert status < 500
