"""Meta-tool definitions for the optimizer.

Provides ``find_tool`` and ``call_tool`` MCP tool definitions and their
handler logic.  The handler functions need a reference to the
:class:`ToolIndex` and the MCP server's dispatch function to work.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from mcp import types as mcp_types

logger = logging.getLogger(__name__)

FIND_TOOL_NAME = "find_tool"
CALL_TOOL_NAME = "call_tool"

FIND_TOOL_DEF = mcp_types.Tool(
    name=FIND_TOOL_NAME,
    description=(
        "Search across all available tools by keyword or description. "
        "Returns the top matching tool definitions with their schemas. "
        "Use this first to discover relevant tools before calling them."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — keywords matching tool names or descriptions.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
)

CALL_TOOL_DEF = mcp_types.Tool(
    name=CALL_TOOL_NAME,
    description=(
        "Call any tool by its exact name with the given arguments. "
        "Use find_tool first to discover the tool name and required arguments."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The exact name of the tool to call.",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments to pass to the tool.",
                "default": {},
            },
        },
        "required": ["name"],
    },
)

META_TOOLS: List[mcp_types.Tool] = [FIND_TOOL_DEF, CALL_TOOL_DEF]

DispatchFn = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Any]]


def build_meta_tools(
    keep_list: Optional[List[str]] = None,
) -> List[mcp_types.Tool]:
    """Return the meta-tool list plus any 'always expose' tools.

    Parameters
    ----------
    keep_list:
        Tool names that should always appear alongside the meta-tools.
        The actual Tool objects must be added by the caller (they depend
        on the registry).
    """
    return list(META_TOOLS)
