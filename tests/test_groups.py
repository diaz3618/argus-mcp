"""Tests for argus_mcp.bridge.groups — GroupManager.

Covers:
- Construction from backends with and without .group attributes
- Property queries (groups, group_count, group_of, servers_in, all_servers)
- Mutation (add_server, remove_server, re-assignment, empty group cleanup)
- Serialization (to_dict, group_summary)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from argus_mcp.bridge.groups import DEFAULT_GROUP, GroupManager


def _make_backends(**groups: str) -> dict:
    """Create a dict of {name: SimpleNamespace(group=...)} for testing."""
    return {name: SimpleNamespace(group=group) for name, group in groups.items()}


class TestGroupManagerConstruction:
    def test_empty_backends(self):
        gm = GroupManager({})
        assert gm.groups == []
        assert gm.group_count == 0
        assert gm.all_servers() == frozenset()

    def test_single_backend_default_group(self):
        gm = GroupManager({"s1": SimpleNamespace(group=None)})
        assert gm.groups == [DEFAULT_GROUP]
        assert gm.group_of("s1") == DEFAULT_GROUP
        assert gm.servers_in(DEFAULT_GROUP) == frozenset({"s1"})

    def test_explicit_groups(self):
        backends = _make_backends(a="alpha", b="alpha", c="beta")
        gm = GroupManager(backends)
        assert sorted(gm.groups) == ["alpha", "beta"]
        assert gm.group_count == 2
        assert gm.servers_in("alpha") == frozenset({"a", "b"})
        assert gm.servers_in("beta") == frozenset({"c"})

    def test_missing_group_attribute_falls_back_to_default(self):
        """Backend config without .group attribute should use DEFAULT_GROUP."""
        gm = GroupManager({"s1": object()})  # no group attr
        assert gm.group_of("s1") == DEFAULT_GROUP

    def test_empty_string_group_falls_back_to_default(self):
        gm = GroupManager({"s1": SimpleNamespace(group="")})
        assert gm.group_of("s1") == DEFAULT_GROUP


class TestGroupManagerQueries:
    @pytest.fixture
    def gm(self):
        backends = _make_backends(s1="web", s2="web", s3="data", s4="data", s5="other")
        return GroupManager(backends)

    def test_groups_sorted(self, gm):
        assert gm.groups == ["data", "other", "web"]

    def test_group_count(self, gm):
        assert gm.group_count == 3

    def test_group_of_known(self, gm):
        assert gm.group_of("s1") == "web"
        assert gm.group_of("s3") == "data"

    def test_group_of_unknown_returns_default(self, gm):
        assert gm.group_of("nonexistent") == DEFAULT_GROUP

    def test_servers_in_known_group(self, gm):
        assert gm.servers_in("web") == frozenset({"s1", "s2"})

    def test_servers_in_unknown_group_returns_empty(self, gm):
        assert gm.servers_in("nonexistent") == frozenset()

    def test_all_servers(self, gm):
        assert gm.all_servers() == frozenset({"s1", "s2", "s3", "s4", "s5"})

    def test_group_summary(self, gm):
        summary = gm.group_summary()
        assert set(summary.keys()) == {"data", "other", "web"}
        assert summary["web"] == ["s1", "s2"]  # sorted


class TestGroupManagerMutation:
    def test_add_server_new(self):
        gm = GroupManager({})
        gm.add_server("s1", "alpha")
        assert gm.group_of("s1") == "alpha"
        assert gm.servers_in("alpha") == frozenset({"s1"})

    def test_add_server_default_group(self):
        gm = GroupManager({})
        gm.add_server("s1")
        assert gm.group_of("s1") == DEFAULT_GROUP

    def test_add_server_reassignment(self):
        gm = GroupManager(_make_backends(s1="old"))
        gm.add_server("s1", "new")
        assert gm.group_of("s1") == "new"
        assert gm.servers_in("new") == frozenset({"s1"})
        # Old group should be cleaned up since it's now empty
        assert "old" not in gm.groups

    def test_add_server_reassignment_keeps_nonempty_group(self):
        gm = GroupManager(_make_backends(s1="shared", s2="shared"))
        gm.add_server("s1", "other")
        assert gm.group_of("s1") == "other"
        assert gm.servers_in("shared") == frozenset({"s2"})
        assert "shared" in gm.groups

    def test_remove_server(self):
        gm = GroupManager(_make_backends(s1="alpha", s2="alpha"))
        gm.remove_server("s1")
        assert "s1" not in gm.all_servers()
        assert gm.servers_in("alpha") == frozenset({"s2"})

    def test_remove_last_server_cleans_group(self):
        gm = GroupManager(_make_backends(s1="solo"))
        gm.remove_server("s1")
        assert "solo" not in gm.groups
        assert gm.group_count == 0

    def test_remove_unknown_server_is_noop(self):
        gm = GroupManager({})
        gm.remove_server("nonexistent")  # should not raise


class TestGroupManagerSerialization:
    def test_to_dict_structure(self):
        gm = GroupManager(_make_backends(a="g1", b="g1", c="g2"))
        d = gm.to_dict()
        assert "groups" in d
        assert "total_groups" in d
        assert "total_servers" in d
        assert d["total_groups"] == 2
        assert d["total_servers"] == 3
        assert d["groups"]["g1"]["count"] == 2
        assert sorted(d["groups"]["g1"]["servers"]) == ["a", "b"]

    def test_to_dict_empty(self):
        gm = GroupManager({})
        d = gm.to_dict()
        assert d["total_groups"] == 0
        assert d["total_servers"] == 0
        assert d["groups"] == {}
