"""Tests for argus_mcp.config.diff — config comparison and diff utilities.

Covers:
- ConfigDiff (has_changes, summary, frozen)
- configs_differ (type mismatch, stdio, sse, streamable-http, fallback)
- compute_diff (added, removed, changed, unchanged)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from argus_mcp.config.diff import ConfigDiff, compute_diff, configs_differ

# ConfigDiff


class TestConfigDiff:
    def test_no_changes(self):
        d = ConfigDiff()
        assert d.has_changes is False
        assert d.summary() == "+0 -0 ~0"

    def test_added(self):
        d = ConfigDiff(added={"a", "b"})
        assert d.has_changes is True
        assert "+2" in d.summary()

    def test_removed(self):
        d = ConfigDiff(removed={"c"})
        assert d.has_changes is True
        assert "-1" in d.summary()

    def test_changed(self):
        d = ConfigDiff(changed={"x"})
        assert d.has_changes is True
        assert "~1" in d.summary()

    def test_all_fields(self):
        d = ConfigDiff(added={"a"}, removed={"b"}, changed={"c"})
        assert d.has_changes is True
        s = d.summary()
        assert "+1" in s
        assert "-1" in s
        assert "~1" in s

    def test_frozen(self):
        d = ConfigDiff()
        with pytest.raises(AttributeError):
            d.added = {"new"}


# configs_differ


class TestConfigsDiffer:
    def test_type_mismatch(self):
        assert configs_differ({"type": "stdio"}, {"type": "sse"}) is True

    def test_same_unknown_type(self):
        """Unknown type falls through to return False."""
        assert configs_differ({"type": "custom"}, {"type": "custom"}) is False

    # stdio

    def test_stdio_identical(self):
        params = SimpleNamespace(command="python", args=["-m", "srv"], env=None)
        old = {"type": "stdio", "params": params}
        new = {
            "type": "stdio",
            "params": SimpleNamespace(command="python", args=["-m", "srv"], env=None),
        }
        assert configs_differ(old, new) is False

    def test_stdio_command_changed(self):
        old = {"type": "stdio", "params": SimpleNamespace(command="python", args=[], env=None)}
        new = {"type": "stdio", "params": SimpleNamespace(command="node", args=[], env=None)}
        assert configs_differ(old, new) is True

    def test_stdio_args_changed(self):
        old = {"type": "stdio", "params": SimpleNamespace(command="p", args=["a"], env=None)}
        new = {"type": "stdio", "params": SimpleNamespace(command="p", args=["b"], env=None)}
        assert configs_differ(old, new) is True

    def test_stdio_env_changed(self):
        old = {"type": "stdio", "params": SimpleNamespace(command="p", args=[], env={"A": "1"})}
        new = {"type": "stdio", "params": SimpleNamespace(command="p", args=[], env={"A": "2"})}
        assert configs_differ(old, new) is True

    def test_stdio_params_one_none(self):
        old = {"type": "stdio", "params": None}
        new = {"type": "stdio", "params": SimpleNamespace(command="p")}
        assert configs_differ(old, new) is True

    def test_stdio_both_params_none(self):
        old = {"type": "stdio", "params": None}
        new = {"type": "stdio", "params": None}
        assert configs_differ(old, new) is False

    # sse

    def test_sse_identical(self):
        base = {
            "type": "sse",
            "url": "http://x",
            "command": "c",
            "args": [],
            "env": {},
            "headers": {},
            "auth": None,
        }
        assert configs_differ(dict(base), dict(base)) is False

    def test_sse_url_changed(self):
        old = {"type": "sse", "url": "http://a"}
        new = {"type": "sse", "url": "http://b"}
        assert configs_differ(old, new) is True

    def test_sse_headers_changed(self):
        old = {"type": "sse", "url": "http://a", "headers": {"X": "1"}}
        new = {"type": "sse", "url": "http://a", "headers": {"X": "2"}}
        assert configs_differ(old, new) is True

    # streamable-http

    def test_streamable_identical(self):
        base = {"type": "streamable-http", "url": "http://x", "headers": {}, "auth": None}
        assert configs_differ(dict(base), dict(base)) is False

    def test_streamable_url_changed(self):
        old = {"type": "streamable-http", "url": "http://a"}
        new = {"type": "streamable-http", "url": "http://b"}
        assert configs_differ(old, new) is True

    def test_streamable_auth_changed(self):
        old = {"type": "streamable-http", "url": "http://a", "auth": None}
        new = {"type": "streamable-http", "url": "http://a", "auth": {"type": "static"}}
        assert configs_differ(old, new) is True


# compute_diff


class TestComputeDiff:
    def test_empty_both(self):
        d = compute_diff({}, {})
        assert d.has_changes is False

    def test_added(self):
        d = compute_diff({}, {"new1": {"type": "sse"}})
        assert d.added == {"new1"}
        assert len(d.removed) == 0
        assert len(d.changed) == 0

    def test_removed(self):
        d = compute_diff({"old1": {"type": "sse"}}, {})
        assert d.removed == {"old1"}
        assert len(d.added) == 0

    def test_changed(self):
        old = {"srv": {"type": "sse", "url": "http://a"}}
        new = {"srv": {"type": "sse", "url": "http://b"}}
        d = compute_diff(old, new)
        assert d.changed == {"srv"}

    def test_unchanged(self):
        base = {"type": "streamable-http", "url": "http://x", "headers": {}, "auth": None}
        d = compute_diff({"srv": dict(base)}, {"srv": dict(base)})
        assert d.has_changes is False

    def test_mixed(self):
        old = {
            "kept": {"type": "streamable-http", "url": "http://x", "headers": {}, "auth": None},
            "removed_srv": {"type": "sse"},
            "changed_srv": {"type": "sse", "url": "http://old"},
        }
        new = {
            "kept": {"type": "streamable-http", "url": "http://x", "headers": {}, "auth": None},
            "added_srv": {"type": "stdio"},
            "changed_srv": {"type": "sse", "url": "http://new"},
        }
        d = compute_diff(old, new)
        assert d.added == {"added_srv"}
        assert d.removed == {"removed_srv"}
        assert d.changed == {"changed_srv"}
