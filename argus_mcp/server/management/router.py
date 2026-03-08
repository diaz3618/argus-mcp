"""Management API router — read-only endpoints for Phase 0.2.

All routes are mounted under ``/manage/v1/`` by ``server/app.py``.
Authentication is added in Phase 0.3.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, Router

from argus_mcp._task_utils import _log_task_exception
from argus_mcp.constants import SERVER_VERSION, SSE_PATH, STREAMABLE_HTTP_PATH
from argus_mcp.runtime.service import ArgusService
from argus_mcp.server.management.schemas import (
    BackendCapabilities,
    BackendDetail,
    BackendHealth,
    BackendsResponse,
    CapabilitiesResponse,
    ErrorResponse,
    EventItem,
    EventsResponse,
    HealthBackends,
    HealthResponse,
    PromptDetail,
    ReconnectResponse,
    ReloadResponse,
    ResourceDetail,
    SessionDetail,
    SessionsResponse,
    ShutdownResponse,
    StatusConfig,
    StatusResponse,
    StatusService,
    StatusTransport,
    ToolDetail,
)

logger = logging.getLogger(__name__)

# Strong references to background tasks to prevent GC before completion
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

SSE_HEARTBEAT_INTERVAL = 30  # seconds


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_service(request: Request) -> ArgusService:
    """Retrieve the ArgusService instance from app state."""
    service: Optional[ArgusService] = getattr(request.app.state, "argus_service", None)
    if service is None:
        raise RuntimeError("ArgusService not found on app.state")
    return service


def _error_json(error: str, message: str, status_code: int = 500) -> JSONResponse:
    body = ErrorResponse(error=error, message=message)
    return JSONResponse(body.model_dump(), status_code=status_code)


def _get_feature_flags() -> Dict[str, bool]:
    """Return feature flags from the mcp_server instance, or empty dict."""
    from argus_mcp.server.app import mcp_server

    ff = getattr(mcp_server, "feature_flags", None)
    if ff is None:
        return {}
    return ff.all_flags()


# ── GET /manage/v1/health ────────────────────────────────────────────────


async def handle_health(request: Request) -> JSONResponse:
    """Liveness probe — always public, returns 200 when process is alive."""
    service = _get_service(request)
    svc_status = service.get_status()

    # Derive health status
    if svc_status.backends_connected == svc_status.backends_total and svc_status.backends_total > 0:
        health = "healthy"
    elif svc_status.backends_connected > 0:
        health = "degraded"
    elif svc_status.backends_total == 0:
        health = "healthy"  # no backends configured is still healthy
    else:
        health = "unhealthy"

    resp = HealthResponse(
        status=health,
        uptime_seconds=svc_status.uptime_seconds,
        version=SERVER_VERSION,
        backends=HealthBackends(
            total=svc_status.backends_total,
            connected=svc_status.backends_connected,
            healthy=svc_status.backends_connected,  # approximate for now
        ),
    )
    return JSONResponse(resp.model_dump())


# ── GET /manage/v1/status ───────────────────────────────────────────────


async def handle_status(request: Request) -> JSONResponse:
    """Full service status including runtime state, config, and transport."""
    service = _get_service(request)
    svc_status = service.get_status()

    # host/port are set during server startup from CLI args (not user request data)
    host = getattr(request.app.state, "host", "127.0.0.1")  # nosec: not user-controlled
    port = getattr(request.app.state, "port", 0)  # nosec: not user-controlled
    sse_url = f"http://{host}:{port}{SSE_PATH}"
    streamable_http_url = f"http://{host}:{port}{STREAMABLE_HTTP_PATH}"

    resp = StatusResponse(
        service=StatusService(
            name=svc_status.server_name,
            version=svc_status.server_version,
            state=svc_status.state.value,
            uptime_seconds=svc_status.uptime_seconds,
            started_at=svc_status.started_at.isoformat() if svc_status.started_at else None,
        ),
        config=StatusConfig(
            file_path=svc_status.config_path,
            loaded_at=svc_status.started_at.isoformat() if svc_status.started_at else None,
            backend_count=svc_status.backends_total,
        ),
        transport=StatusTransport(
            sse_url=sse_url,
            streamable_http_url=streamable_http_url,
            host=host,
            port=port,
        ),
        feature_flags=_get_feature_flags(),
    )
    return JSONResponse(resp.model_dump())


# ── GET /manage/v1/backends ─────────────────────────────────────────────


async def handle_backends(request: Request) -> JSONResponse:
    """List all backend server connections with their status."""
    service = _get_service(request)
    route_map = service.registry.get_route_map()

    # Count capabilities per backend
    caps_per_backend: Dict[str, Dict[str, int]] = {}
    for _cap_name, (svr_name, _orig) in route_map.items():
        if svr_name not in caps_per_backend:
            caps_per_backend[svr_name] = {"tools": 0, "resources": 0, "prompts": 0}
        # We only have the route map which doesn't distinguish type easily.
        # Count tools (all route_map entries are capabilities).
        caps_per_backend[svr_name]["tools"] += 1

    # Build more accurate per-backend capability counts
    tool_backends: Dict[str, int] = {}
    resource_backends: Dict[str, int] = {}
    prompt_backends: Dict[str, int] = {}

    for tool in service.tools:
        entry = route_map.get(tool.name)
        if entry:
            svr = entry[0]
            tool_backends[svr] = tool_backends.get(svr, 0) + 1

    for resource in service.resources:
        rname = resource.name if hasattr(resource, "name") else str(resource.uri)
        entry = route_map.get(rname)
        if entry:
            svr = entry[0]
            resource_backends[svr] = resource_backends.get(svr, 0) + 1

    for prompt in service.prompts:
        entry = route_map.get(prompt.name)
        if entry:
            svr = entry[0]
            prompt_backends[svr] = prompt_backends.get(svr, 0) + 1

    backends = []
    svc_status = service.get_status()
    health_checker = service.health_checker
    for bi in svc_status.backends:
        # Use real health data when available
        health_detail: Dict[str, Any] = {"status": "unknown"}
        if health_checker is not None:
            bh = health_checker.get_health(bi.name)
            if bh is not None:
                health_detail = bh.to_dict()
                health_detail["status"] = bh.state.value
            elif bi.connected:
                health_detail = {"status": "healthy"}
        elif bi.connected:
            health_detail = {"status": "healthy"}

        # Determine group from group manager
        group_name = "default"
        if service.group_manager is not None:
            from argus_mcp.bridge.groups import GroupManager

            gm: GroupManager = service.group_manager  # type: ignore[assignment]
            group_name = gm.group_of(bi.name)

        # Extract status phase and conditions from BackendStatusRecord
        status_phase = "pending"
        status_error: Optional[str] = None
        status_conditions: list = []
        cm = service.manager
        if cm is not None:
            sr = cm.get_status_record(bi.name)
            if sr is not None:
                status_phase = sr.phase.value
                status_error = sr.error
                status_conditions = [c.model_dump(mode="json") for c in sr.recent_conditions]

        backends.append(
            BackendDetail(
                name=bi.name,
                type=bi.type,
                group=group_name,
                phase=status_phase,
                state="connected" if bi.connected else "disconnected",
                error=bi.error or status_error,
                capabilities=BackendCapabilities(
                    tools=tool_backends.get(bi.name, 0),
                    resources=resource_backends.get(bi.name, 0),
                    prompts=prompt_backends.get(bi.name, 0),
                ),
                health=BackendHealth(
                    status=health_detail.get("status", "unknown"),
                ),
                conditions=status_conditions,
            )
        )

    resp = BackendsResponse(backends=backends)
    return JSONResponse(resp.model_dump())


# ── GET /manage/v1/groups ───────────────────────────────────────────────


async def handle_groups(request: Request) -> JSONResponse:
    """List all server groups and their members.

    Query parameters:
        group (str): Filter to a specific group name.
    """
    service = _get_service(request)
    filter_group = request.query_params.get("group")

    if service.group_manager is None:
        return JSONResponse({"groups": {}, "total_groups": 0, "total_servers": 0})

    from argus_mcp.bridge.groups import GroupManager

    gm: GroupManager = service.group_manager  # type: ignore[assignment]

    if filter_group:
        servers = sorted(gm.servers_in(filter_group))
        return JSONResponse(
            {
                "groups": {
                    filter_group: {"servers": servers, "count": len(servers)},
                },
                "total_groups": 1 if servers else 0,
                "total_servers": len(servers),
            }
        )

    return JSONResponse(gm.to_dict())


# ── GET /manage/v1/capabilities ─────────────────────────────────────────


async def handle_capabilities(request: Request) -> JSONResponse:
    """Aggregated capabilities from all connected backends."""
    service = _get_service(request)
    route_map = service.registry.get_route_map()

    # Query parameters
    filter_type = request.query_params.get("type")
    filter_backend = request.query_params.get("backend")
    filter_search = request.query_params.get("search", "").lower()

    tools = []
    resources = []
    prompts = []

    # Tools
    if filter_type is None or filter_type == "tools":
        for tool in service.tools:
            entry = route_map.get(tool.name)
            backend_name = entry[0] if entry else ""
            original_name = entry[1] if entry else tool.name

            if filter_backend and backend_name != filter_backend:
                continue
            if filter_search and filter_search not in tool.name.lower():
                continue

            tools.append(
                ToolDetail(
                    name=tool.name,
                    original_name=original_name,
                    description=tool.description or "",
                    backend=backend_name,
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                )
            )

    # Resources
    if filter_type is None or filter_type == "resources":
        for resource in service.resources:
            rname = resource.name if hasattr(resource, "name") else ""
            ruri = str(resource.uri) if hasattr(resource, "uri") else ""
            entry = route_map.get(rname)
            backend_name = entry[0] if entry else ""

            if filter_backend and backend_name != filter_backend:
                continue
            if filter_search and filter_search not in rname.lower():
                continue

            resources.append(
                ResourceDetail(
                    uri=ruri,
                    name=rname,
                    backend=backend_name,
                    mime_type=getattr(resource, "mimeType", None),
                )
            )

    # Prompts
    if filter_type is None or filter_type == "prompts":
        for prompt in service.prompts:
            entry = route_map.get(prompt.name)
            backend_name = entry[0] if entry else ""

            if filter_backend and backend_name != filter_backend:
                continue
            if filter_search and filter_search not in prompt.name.lower():
                continue

            prompts.append(
                PromptDetail(
                    name=prompt.name,
                    description=prompt.description or "",
                    backend=backend_name,
                    arguments=list(prompt.arguments) if prompt.arguments else [],
                )
            )

    resp = CapabilitiesResponse(
        tools=tools,
        resources=resources,
        prompts=prompts,
        route_map=route_map,
    )
    return JSONResponse(resp.model_dump())


# ── GET /manage/v1/events ───────────────────────────────────────────────


async def handle_events(request: Request) -> JSONResponse:
    """Recent events (polling)."""
    service = _get_service(request)

    limit = int(request.query_params.get("limit", "100"))
    since = request.query_params.get("since")
    severity = request.query_params.get("severity")

    raw_events = service.get_events(limit=limit, since=since, severity=severity)
    items = [
        EventItem(
            id=e["id"],
            timestamp=e["timestamp"],
            stage=e["stage"],
            message=e["message"],
            severity=e.get("severity", "info"),
            backend=e.get("backend"),
            details=e.get("details"),
        )
        for e in raw_events
    ]

    resp = EventsResponse(events=items)
    return JSONResponse(resp.model_dump())


# ── GET /manage/v1/events/stream ────────────────────────────────────────


async def handle_events_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events stream for real-time event delivery."""
    service = _get_service(request)

    async def event_generator():
        queue = service.subscribe()
        try:
            # Send initial heartbeat
            yield _sse_format("heartbeat", {"message": "connected"}, "hb-0")

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    yield _sse_format(
                        event.get("stage", "event"),
                        event,
                        event.get("id", ""),
                    )
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield _sse_format("heartbeat", {"message": "ping"})
        except asyncio.CancelledError:
            logger.debug("SSE event stream client disconnected.")
        finally:
            service.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_format(
    event_type: str,
    data: Any,
    event_id: Optional[str] = None,
) -> str:
    """Format a Server-Sent Event string."""
    parts = [f"event: {event_type}"]
    parts.append(f"data: {json.dumps(data, default=str)}")
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("\n")
    return "\n".join(parts)


# ── POST /manage/v1/reload ──────────────────────────────────────────────


async def handle_reload(request: Request) -> JSONResponse:
    """Hot-reload config and reconnect changed backends."""
    service = _get_service(request)

    if not service.is_running:
        return _error_json("service_unavailable", "Service is not running.", 503)

    result = await service.reload()
    resp = ReloadResponse(**result)
    return JSONResponse(resp.model_dump())


# ── POST /manage/v1/reconnect/{name} ────────────────────────────────────


async def handle_reconnect(request: Request) -> JSONResponse:
    """Reconnect a specific backend by name."""
    service = _get_service(request)
    name = request.path_params.get("name", "")

    if not name:
        return _error_json("bad_request", "Backend name is required.", 400)

    if not service.is_running:
        return _error_json("service_unavailable", "Service is not running.", 503)

    # Check if backend exists
    if service.config_data and name not in service.config_data:
        return _error_json("not_found", f"Backend '{name}' not found.", 404)

    result = await service.reconnect_backend(name)
    resp = ReconnectResponse(**result)
    status_code = 200 if resp.reconnected else 500
    return JSONResponse(resp.model_dump(), status_code=status_code)


# ── POST /manage/v1/shutdown ────────────────────────────────────────────


async def handle_shutdown(request: Request) -> JSONResponse:
    """Graceful server shutdown with backend cleanup."""
    service = _get_service(request)

    # Parse optional timeout from request body
    timeout = 30
    try:
        body = await request.json()
        timeout = int(body.get("timeout_seconds", 30))
    except Exception:
        logger.debug(
            "Failed to parse shutdown timeout from request body, using default", exc_info=True
        )

    resp = ShutdownResponse(shutting_down=True)
    # Schedule shutdown in background so we can return the response first
    task = asyncio.create_task(
        _deferred_shutdown(service, timeout),
        name="management_shutdown",
    )
    # Strong reference prevents GC before task completes
    task.add_done_callback(_log_task_exception)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(resp.model_dump())


async def _deferred_shutdown(service: ArgusService, timeout: int) -> None:
    """Run shutdown after a brief delay so the HTTP response can be sent."""
    await asyncio.sleep(0.5)  # Allow response to flush
    await service.shutdown(timeout_seconds=timeout)


# ── GET /manage/v1/sessions ─────────────────────────────────────────────


async def handle_sessions(request: Request) -> JSONResponse:
    """List active client sessions."""
    from argus_mcp.server.app import mcp_server

    session_mgr = getattr(mcp_server, "session_manager", None)
    if session_mgr is None:
        return JSONResponse(SessionsResponse(active_sessions=0, sessions=[]).model_dump())

    raw_sessions = session_mgr.list_sessions()
    details = [SessionDetail(**s) for s in raw_sessions]
    resp = SessionsResponse(
        active_sessions=session_mgr.active_count,
        sessions=details,
    )
    return JSONResponse(resp.model_dump())


# ── Router ───────────────────────────────────────────────────────────────


management_routes = Router(
    routes=[
        Route("/health", endpoint=handle_health, methods=["GET"]),
        Route("/status", endpoint=handle_status, methods=["GET"]),
        Route("/backends", endpoint=handle_backends, methods=["GET"]),
        Route("/groups", endpoint=handle_groups, methods=["GET"]),
        Route("/capabilities", endpoint=handle_capabilities, methods=["GET"]),
        Route("/sessions", endpoint=handle_sessions, methods=["GET"]),
        Route("/events", endpoint=handle_events, methods=["GET"]),
        Route("/events/stream", endpoint=handle_events_stream, methods=["GET"]),
        Route("/reload", endpoint=handle_reload, methods=["POST"]),
        Route("/reconnect/{name}", endpoint=handle_reconnect, methods=["POST"]),
        Route("/shutdown", endpoint=handle_shutdown, methods=["POST"]),
    ]
)
