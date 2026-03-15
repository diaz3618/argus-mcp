"""Tests for argus_mcp.server.session.models — MCPSession dataclass."""

import time

from argus_mcp.server.session.models import MCPSession


class TestMCPSessionCreation:
    def test_defaults(self):
        s = MCPSession()
        assert len(s.id) == 36  # uuid4 string: 8-4-4-4-12
        assert s.routing_table == {}
        assert s.capability_snapshot == {}
        assert s.ttl == 1800.0
        assert s.transport_type == ""
        assert s.created_at > 0
        assert s.last_active > 0

    def test_unique_ids(self):
        ids = {MCPSession().id for _ in range(50)}
        assert len(ids) == 50

    def test_custom_values(self):
        s = MCPSession(
            routing_table={"search": "github", "read": "fs"},
            capability_snapshot={"tools": 2, "resources": 0, "prompts": 0},
            ttl=600.0,
            transport_type="sse",
        )
        assert s.routing_table["search"] == "github"
        assert s.capability_snapshot["tools"] == 2
        assert s.ttl == 600.0
        assert s.transport_type == "sse"


class TestMCPSessionExpired:
    def test_not_expired_when_fresh(self):
        s = MCPSession(ttl=1800.0)
        assert s.expired is False

    def test_expired_when_idle_exceeds_ttl(self):
        s = MCPSession(ttl=0.0)
        # With TTL of 0, any positive idle time means expired
        # Give a tiny sleep to ensure monotonic advances
        time.sleep(0.01)
        assert s.expired is True

    def test_not_expired_with_large_ttl(self):
        s = MCPSession(ttl=999999.0)
        assert s.expired is False


class TestMCPSessionAgeAndIdle:
    def test_age_seconds_increases(self):
        s = MCPSession()
        time.sleep(0.05)
        assert s.age_seconds >= 0.04

    def test_idle_seconds_increases(self):
        s = MCPSession()
        time.sleep(0.05)
        assert s.idle_seconds >= 0.04

    def test_touch_resets_idle(self):
        s = MCPSession()
        time.sleep(0.05)
        idle_before = s.idle_seconds
        s.touch()
        idle_after = s.idle_seconds
        # After touch, idle should be much smaller than before
        assert idle_after < idle_before

    def test_touch_does_not_reset_age(self):
        s = MCPSession()
        time.sleep(0.05)
        age_before = s.age_seconds
        s.touch()
        age_after = s.age_seconds
        # Age continues to grow after touch
        assert age_after >= age_before


class TestResolveBackend:
    def test_found(self):
        s = MCPSession(routing_table={"search": "github", "read": "fs"})
        assert s.resolve_backend("search") == "github"
        assert s.resolve_backend("read") == "fs"

    def test_not_found(self):
        s = MCPSession(routing_table={"search": "github"})
        assert s.resolve_backend("nonexistent") is None

    def test_empty_routing(self):
        s = MCPSession()
        assert s.resolve_backend("anything") is None


class TestToDict:
    def test_structure(self):
        s = MCPSession(
            routing_table={"search": "github", "read": "fs"},
            capability_snapshot={"tools": 2},
            transport_type="sse",
            ttl=600.0,
        )
        d = s.to_dict()
        assert d["id"] == s.id
        assert d["transport_type"] == "sse"
        assert d["tool_count"] == 2  # len(routing_table)
        assert d["capability_snapshot"] == {"tools": 2}
        assert d["ttl"] == 600.0
        assert isinstance(d["age_seconds"], float)
        assert isinstance(d["idle_seconds"], float)
        assert isinstance(d["expired"], bool)
        # age and idle should be rounded to 1 decimal
        assert d["age_seconds"] == round(d["age_seconds"], 1)
        assert d["idle_seconds"] == round(d["idle_seconds"], 1)

    def test_tool_count_matches_routing_table_size(self):
        s = MCPSession(routing_table={"a": "b", "c": "d", "e": "f"})
        assert s.to_dict()["tool_count"] == 3

    def test_empty_routing_gives_zero_count(self):
        s = MCPSession()
        assert s.to_dict()["tool_count"] == 0

    def test_expired_in_dict(self):
        s = MCPSession(ttl=0.0)
        time.sleep(0.01)
        d = s.to_dict()
        assert d["expired"] is True


class TestMCPSessionIsolation:
    """Ensure each session has independent mutable fields."""

    def test_routing_tables_independent(self):
        s1 = MCPSession()
        s2 = MCPSession()
        s1.routing_table["tool"] = "backend_a"
        assert "tool" not in s2.routing_table

    def test_capability_snapshots_independent(self):
        s1 = MCPSession()
        s2 = MCPSession()
        s1.capability_snapshot["tools"] = 5
        assert "tools" not in s2.capability_snapshot
