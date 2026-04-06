"""Tests for find_tool dispatch fix (SEC-02).

Verifies that the ``find_tool`` meta-tool is routed through
``_dispatch()`` and never bypasses the middleware chain.
"""

from __future__ import annotations

import inspect

import pytest

from argus_mcp.server import handlers as handlers_mod

pytestmark = [pytest.mark.security]


class TestFindToolDispatchFix:
    """Confirm find_tool no longer shortcuts to optimizer.search()."""

    def test_find_tool_calls_dispatch(self):
        """The FIND_TOOL_NAME branch must call _dispatch(), not optimizer.search()."""
        src = inspect.getsource(handlers_mod.register_handlers)
        # The old bypass called optimizer.search() directly — must be gone
        assert "optimizer.search(" not in src

    def test_find_tool_uses_dispatch(self):
        """The FIND_TOOL_NAME branch should route through _dispatch."""
        src = inspect.getsource(handlers_mod.register_handlers)
        # Verify _dispatch is called for FIND_TOOL_NAME handling
        assert "_dispatch(mcp_server" in src

    def test_no_direct_json_dumps_for_find(self):
        """No inline json.dumps(results) pattern for find_tool shortcut."""
        src = inspect.getsource(handlers_mod.register_handlers)
        # The old pattern built CallToolResult with json.dumps(results)
        # directly from optimizer.search().  It should not exist anymore.
        # call_tool (CALL_TOOL_NAME) delegates via _dispatch so it never
        # builds results from optimizer.search either.
        assert "json.dumps(results" not in src
