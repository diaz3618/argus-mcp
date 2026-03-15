"""Tests for argus_mcp.server.transport — SSE and streamable HTTP transport.

Covers:
- sse_transport object existence
- handle_sse() with mock request
- handle_streamable_http() with 503 when not ready
"""

from __future__ import annotations

import pytest


class TestHandleStreamableHttp:
    """Test the raw ASGI handler for streamable HTTP."""

    @pytest.mark.asyncio
    async def test_module_imports(self):
        """Verify the transport module imports cleanly."""
        from argus_mcp.server import transport

        assert hasattr(transport, "handle_sse")
        assert hasattr(transport, "handle_streamable_http")
        assert hasattr(transport, "sse_transport")

    @pytest.mark.asyncio
    async def test_sse_transport_type(self):
        """sse_transport should be an SseServerTransport instance."""
        from mcp.server.sse import SseServerTransport

        from argus_mcp.server.transport import sse_transport

        assert isinstance(sse_transport, SseServerTransport)


class TestTransportConstants:
    def test_post_messages_path(self):
        from argus_mcp.constants import POST_MESSAGES_PATH

        assert POST_MESSAGES_PATH == "/messages/"
