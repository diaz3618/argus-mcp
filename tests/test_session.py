"""Tests for session management"""

from __future__ import annotations

import asyncio

import pytest

from argus_mcp.server.session.manager import SessionManager
from argus_mcp.server.session.models import MCPSession

#  MCPSession model tests


class TestMCPSession:
    def test_default_creation(self) -> None:
        s = MCPSession()
        assert s.id
        assert s.routing_table == {}
        assert s.ttl == 1800.0
        assert not s.expired

    def test_routing_table_stored(self) -> None:
        rt = {"tool_a": "backend_1", "tool_b": "backend_2"}
        s = MCPSession(routing_table=rt)
        assert s.routing_table == rt
        assert s.resolve_backend("tool_a") == "backend_1"

    def test_resolve_backend(self) -> None:
        s = MCPSession(routing_table={"tool_a": "backend_1"})
        assert s.resolve_backend("tool_a") == "backend_1"
        assert s.resolve_backend("nonexistent") is None

    def test_touch_updates_last_active(self) -> None:
        s = MCPSession()
        old_active = s.last_active
        s.touch()
        assert s.last_active >= old_active

    def test_expired_with_tiny_ttl(self) -> None:
        s = MCPSession(ttl=0.0)
        # With TTL=0, it's expired immediately after creation (monotonic advanced)
        assert s.expired

    def test_age_and_idle(self) -> None:
        s = MCPSession()
        assert s.age_seconds >= 0
        assert s.idle_seconds >= 0

    def test_to_dict(self) -> None:
        s = MCPSession(
            routing_table={"a": "b"},
            capability_snapshot={"tools": 5},
            transport_type="sse",
        )
        d = s.to_dict()
        assert d["id"] == s.id
        assert d["transport_type"] == "sse"
        assert d["tool_count"] == 1
        assert d["capability_snapshot"] == {"tools": 5}
        assert "age_seconds" in d
        assert "idle_seconds" in d
        assert "ttl" in d
        assert "expired" in d


#  SessionManager tests


class TestSessionManager:
    def test_create_session(self) -> None:
        sm = SessionManager()
        s = sm.create_session(
            routing_table={"tool_a": "backend_1"},
            transport_type="sse",
        )
        assert s.id
        assert s.routing_table == {"tool_a": "backend_1"}
        assert s.transport_type == "sse"
        assert sm.active_count == 1

    def test_create_session_with_custom_id(self) -> None:
        sm = SessionManager()
        s = sm.create_session(
            routing_table={},
            session_id="custom-123",
        )
        assert s.id == "custom-123"

    def test_get_session(self) -> None:
        sm = SessionManager()
        s = sm.create_session(routing_table={"a": "b"})
        retrieved = sm.get_session(s.id)
        assert retrieved is not None
        assert retrieved.id == s.id

    def test_get_nonexistent_session(self) -> None:
        sm = SessionManager()
        assert sm.get_session("nonexistent") is None

    def test_get_expired_session_returns_none(self) -> None:
        sm = SessionManager(default_ttl=0.0)
        s = sm.create_session(routing_table={})
        assert sm.get_session(s.id) is None

    def test_remove_session(self) -> None:
        sm = SessionManager()
        s = sm.create_session(routing_table={})
        assert sm.remove_session(s.id)
        assert sm.active_count == 0
        assert not sm.remove_session(s.id)

    def test_list_sessions(self) -> None:
        sm = SessionManager()
        sm.create_session(routing_table={"a": "b"}, transport_type="sse")
        sm.create_session(routing_table={"c": "d"}, transport_type="streamable_http")
        sessions = sm.list_sessions()
        assert len(sessions) == 2
        types = {s["transport_type"] for s in sessions}
        assert types == {"sse", "streamable_http"}

    def test_capability_snapshot(self) -> None:
        sm = SessionManager()
        s = sm.create_session(
            routing_table={},
            capability_snapshot={"tools": 10, "resources": 2, "prompts": 1},
        )
        assert s.capability_snapshot == {"tools": 10, "resources": 2, "prompts": 1}

    def test_immutable_routing_after_creation(self) -> None:
        """Session's routing table should be independent of original dict."""
        sm = SessionManager()
        rt = {"tool1": "backend1"}
        s = sm.create_session(routing_table=rt)
        rt["tool2"] = "backend2"
        assert "tool2" not in s.routing_table

    def test_multiple_sessions_independent(self) -> None:
        sm = SessionManager()
        s1 = sm.create_session(routing_table={"a": "b"})
        s2 = sm.create_session(routing_table={"c": "d"})
        assert s1.id != s2.id
        assert sm.active_count == 2


@pytest.mark.asyncio
class TestSessionManagerAsync:
    async def test_start_stop(self) -> None:
        sm = SessionManager(cleanup_interval=0.1)
        sm.start()
        sm.create_session(routing_table={})
        await sm.stop()
        assert sm.active_count == 0

    async def test_cleanup_removes_expired(self) -> None:
        sm = SessionManager(default_ttl=0.05, cleanup_interval=0.1)
        sm.start()
        sm.create_session(routing_table={})
        assert sm.active_count == 1
        # Wait for session to expire and cleanup to run
        await asyncio.sleep(0.25)
        assert sm.active_count == 0
        await sm.stop()
