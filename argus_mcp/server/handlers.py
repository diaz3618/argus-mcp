"""MCP handler functions - registered on the MCP server instance."""

import json
import logging
from typing import Any, Dict, List, Optional

from mcp import types as mcp_types
from mcp.server import Server as McpServer

from argus_mcp.bridge.middleware.chain import RequestContext
from argus_mcp.bridge.optimizer.meta_tools import (
    CALL_TOOL_NAME,
    FIND_TOOL_NAME,
    META_TOOLS,
)
from argus_mcp.errors import BackendServerError
from argus_mcp.server.auth_context import (
    current_auth_token,
    current_client_ip,
    current_session_id,
    current_user,
)
from argus_mcp.server.state import get_state

logger = logging.getLogger(__name__)


async def _dispatch(
    mcp_server: McpServer,
    cap_name: str,
    mcp_method: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    """Route a request through the middleware chain."""
    state = get_state(mcp_server)
    chain = state.middleware_chain
    if chain is None:
        raise RuntimeError("Middleware chain is not initialised on the MCP server instance.")

    # Populate metadata from ASGI auth context (set by transport auth gate)
    metadata: Dict[str, Any] = {}
    user = current_user.get()
    if user is not None:
        metadata["user"] = user
        metadata["user_subject"] = user.subject
    token = current_auth_token.get()
    if token is not None:
        metadata["auth_token"] = token
    session_id = current_session_id.get()  # nosemgrep: mcp-session-not-bound-to-user
    if session_id is not None:
        metadata["session_id"] = session_id
    client_ip = current_client_ip.get()
    if client_ip is not None:
        metadata["client_ip"] = client_ip

    ctx = RequestContext(
        capability_name=cap_name,
        mcp_method=mcp_method,
        arguments=arguments,
        metadata=metadata,
    )
    result = await chain(ctx)
    if ctx.error is not None:
        raise ctx.error
    return result


def register_handlers(mcp_server: McpServer) -> None:
    """Register all MCP protocol handlers on the server instance."""

    @mcp_server.list_tools()
    async def handle_list_tools() -> List[mcp_types.Tool]:
        logger.debug("Handling listTools request...")
        if not mcp_server.registry:
            raise BackendServerError("Registry is not initialized")
        tools = mcp_server.registry.get_aggregated_tools()

        state = get_state(mcp_server)
        composite_tools = state.composite_tools
        for ct in composite_tools:
            info = ct.to_tool_info()
            tools.append(
                mcp_types.Tool(
                    name=info["name"],
                    description=info.get("description", ""),
                    inputSchema=info.get("inputSchema", {}),
                )
            )

        # If optimizer is active, return meta-tools + keep-list only
        optimizer = state.optimizer_index
        optimizer_enabled = state.optimizer_enabled
        if optimizer_enabled and optimizer is not None:
            keep_names = set(state.optimizer_keep_list)
            kept = [t for t in tools if t.name in keep_names]
            result = list(META_TOOLS) + kept
            logger.info(
                "Returning %s tools (optimizer active: %d meta + %d kept)",
                len(result),
                len(META_TOOLS),
                len(kept),
            )
            return result

        logger.info(
            "Returning %s aggregated tools (%d composite)",
            len(tools),
            len(composite_tools),
        )
        return tools

    @mcp_server.list_resources()
    async def handle_list_resources() -> List[mcp_types.Resource]:
        logger.debug("Handling listResources request...")
        if not mcp_server.registry:
            raise BackendServerError("Registry is not initialized")
        resources = mcp_server.registry.get_aggregated_resources()
        logger.info("Returning %s aggregated resources", len(resources))
        return resources

    @mcp_server.list_prompts()
    async def handle_list_prompts() -> List[mcp_types.Prompt]:
        logger.debug("Handling listPrompts request...")
        if not mcp_server.registry:
            raise BackendServerError("Registry is not initialized")
        prompts = mcp_server.registry.get_aggregated_prompts()
        logger.info("Returning %s aggregated prompts", len(prompts))
        return prompts

    @mcp_server.call_tool()
    async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> mcp_types.CallToolResult:
        logger.debug("Handling callTool: name='%s'", name)

        state = get_state(mcp_server)
        optimizer = state.optimizer_index
        optimizer_enabled = state.optimizer_enabled

        if optimizer_enabled and optimizer is not None:
            if name == FIND_TOOL_NAME:
                query = arguments.get("query", "")
                limit = int(arguments.get("limit", 5))
                results = optimizer.search(query, limit=limit)
                return mcp_types.CallToolResult(
                    content=[
                        mcp_types.TextContent(
                            type="text",
                            text=json.dumps(results, indent=2),
                        )
                    ],
                    isError=False,
                )

            if name == CALL_TOOL_NAME:
                # Delegate to the real tool via dispatch
                real_name = arguments.get("name", "")
                real_args = arguments.get("arguments", {})
                if not real_name:
                    raise BackendServerError("call_tool requires a 'name' argument")
                logger.info("Optimizer call_tool dispatching to '%s'", real_name)
                result = await _dispatch(mcp_server, real_name, "call_tool", real_args)
                if isinstance(result, mcp_types.CallToolResult):
                    return result
                raise BackendServerError(
                    f"Backend returned invalid type for tool call '{real_name}'."
                )

        composite_tools = state.composite_tools
        for ct in composite_tools:
            if ct.name == name:
                logger.info("Dispatching composite workflow tool '%s'", name)
                try:
                    output = await ct.invoke(arguments)
                    return mcp_types.CallToolResult(
                        content=[
                            mcp_types.TextContent(
                                type="text",
                                text=(
                                    json.dumps(output, indent=2)
                                    if not isinstance(output, str)
                                    else output
                                ),
                            )
                        ],
                        isError=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    # (final handler boundary — this IS the error handler)
                    logger.error(  # nosemgrep: code-quality-logging-error-without-handling
                        "Composite workflow '%s' failed: %s", name, exc, exc_info=True
                    )
                    raise BackendServerError(
                        f"Composite workflow '{name}' execution failed: {exc}"
                    ) from exc

        result = await _dispatch(mcp_server, name, "call_tool", arguments)
        if isinstance(result, mcp_types.CallToolResult):
            return result
        logger.error(
            "call_tool forwarding returned unexpected type: %s for tool '%s'",
            type(result),
            name,
        )
        raise BackendServerError(f"Backend returned invalid type for tool call '{name}'.")

    @mcp_server.read_resource()
    async def handle_read_resource(name: str) -> mcp_types.ReadResourceResult:
        logger.debug("Handling readResource: name='%s'", name)
        result = await _dispatch(mcp_server, name, "read_resource")
        if isinstance(result, mcp_types.ReadResourceResult):
            return result
        logger.error(
            "read_resource forwarding returned unexpected type: %s for resource '%s'",
            type(result),
            name,
        )
        raise BackendServerError(f"Backend returned invalid type for resource read '{name}'.")

    @mcp_server.get_prompt()
    async def handle_get_prompt(
        name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> mcp_types.GetPromptResult:
        logger.debug("Handling getPrompt: name='%s'", name)
        typed_args: Optional[Dict[str, str]] = None
        if arguments is not None:
            try:
                typed_args = {k: str(v) for k, v in arguments.items()}
            except (TypeError, ValueError):
                logger.warning(
                    "Could not cast get_prompt arguments to Dict[str, str] "
                    "for prompt '%s'. Will fall back to original arguments.",
                    name,
                    exc_info=True,
                )

        result = await _dispatch(mcp_server, name, "get_prompt", typed_args or arguments)
        if isinstance(result, mcp_types.GetPromptResult):
            return result
        logger.error(
            "get_prompt forwarding returned unexpected type: %s for prompt '%s'",
            type(result),
            name,
        )
        raise BackendServerError(f"Backend returned invalid type for prompt '{name}'.")

    logger.debug("All MCP protocol handlers registered on server instance.")
