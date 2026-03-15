"""Management API router — read-only endpoints for Phase 0.2.

All routes are mounted under ``/manage/v1/`` by ``server/app.py``.
Authentication is added in Phase 0.3.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlunparse

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, Router

from argus_mcp._task_utils import _log_task_exception
from argus_mcp.constants import (
    MGMT_BACKEND_NAME_MAX_LEN,
    MGMT_EVENTS_LIMIT_MAX,
    MGMT_EVENTS_LIMIT_MIN,
    MGMT_SHUTDOWN_TIMEOUT_MAX,
    MGMT_SHUTDOWN_TIMEOUT_MIN,
    SERVER_VERSION,
    SSE_HEARTBEAT_INTERVAL,
    SSE_PATH,
    STREAMABLE_HTTP_PATH,
)
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
    ReadyResponse,
    ReAuthResponse,
    ReconnectResponse,
    ReloadResponse,
    ResourceDetail,
    SessionDetail,
    SessionsResponse,
    ShutdownRequest,
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

_BACKEND_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


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

    # Compute actual healthy count from health checker when available
    health_checker = service.health_checker
    if health_checker is not None:
        all_health = health_checker.get_all_health()
        healthy_count = sum(1 for bh in all_health.values() if bh.state.value == "healthy")
    else:
        healthy_count = svc_status.backends_connected  # fallback when no checker

    resp = HealthResponse(
        status=health,
        uptime_seconds=svc_status.uptime_seconds,
        version=SERVER_VERSION,
        backends=HealthBackends(
            total=svc_status.backends_total,
            connected=svc_status.backends_connected,
            healthy=healthy_count,
        ),
    )
    return JSONResponse(resp.model_dump())


async def handle_ready(request: Request) -> JSONResponse:
    """Readiness probe — returns 200 when the gateway is ready to serve traffic."""
    service = _get_service(request)
    is_ready = service._ready_event.is_set()
    if is_ready:
        return JSONResponse(ReadyResponse(ready=True, reason="accepting traffic").model_dump())
    return JSONResponse(
        ReadyResponse(ready=False, reason="backends not connected").model_dump(),
        status_code=503,
    )


async def handle_status(request: Request) -> JSONResponse:
    """Full service status including runtime state, config, and transport."""
    service = _get_service(request)
    svc_status = service.get_status()

    # host/port are set during server startup from CLI args (not user request data)
    host = getattr(request.app.state, "host", "127.0.0.1")  # nosec: not user-controlled
    port = getattr(request.app.state, "port", 0)  # nosec: not user-controlled
    sse_url = urlunparse(("http", f"{host}:{port}", SSE_PATH, "", "", ""))
    streamable_http_url = urlunparse(("http", f"{host}:{port}", STREAMABLE_HTTP_PATH, "", "", ""))

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


async def handle_backends(request: Request) -> JSONResponse:
    """List all backend server connections with their status."""
    service = _get_service(request)
    route_map = service.registry.get_route_map()

    # Build per-backend capability counts
    def _count_by_backend(items, name_fn):
        counts: Dict[str, int] = {}
        for item in items:
            entry = route_map.get(name_fn(item))
            if entry:
                counts[entry[0]] = counts.get(entry[0], 0) + 1
        return counts

    tool_backends = _count_by_backend(service.tools, lambda t: t.name)
    resource_backends = _count_by_backend(
        service.resources,
        lambda r: r.name if hasattr(r, "name") else str(r.uri),
    )
    prompt_backends = _count_by_backend(service.prompts, lambda p: p.name)

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


async def handle_capabilities(request: Request) -> JSONResponse:
    """Aggregated capabilities from all connected backends."""
    service = _get_service(request)
    route_map = service.registry.get_route_map()

    # Query parameters
    filter_type = request.query_params.get("type")
    filter_backend = request.query_params.get("backend")
    filter_search = request.query_params.get("search", "").lower()

    def _filter_caps(type_name, items, name_fn, detail_fn):
        """Filter capabilities by backend/search and build detail objects."""
        if filter_type is not None and filter_type != type_name:
            return []
        result = []
        for item in items:
            cap_name = name_fn(item)
            entry = route_map.get(cap_name)
            backend_name = entry[0] if entry else ""
            if filter_backend and backend_name != filter_backend:
                continue
            if filter_search and filter_search not in cap_name.lower():
                continue
            result.append(detail_fn(item, entry, backend_name))
        return result

    tools = _filter_caps(
        "tools",
        service.tools,
        lambda t: t.name,
        lambda t, entry, bn: ToolDetail(
            name=t.name,
            original_name=entry[1] if entry else t.name,
            description=t.description or "",
            backend=bn,
            input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
        ),
    )
    resources = _filter_caps(
        "resources",
        service.resources,
        lambda r: r.name if hasattr(r, "name") else "",
        lambda r, _entry, bn: ResourceDetail(
            uri=str(r.uri) if hasattr(r, "uri") else "",
            name=r.name if hasattr(r, "name") else "",
            backend=bn,
            mime_type=getattr(r, "mimeType", None),
        ),
    )
    prompts = _filter_caps(
        "prompts",
        service.prompts,
        lambda p: p.name,
        lambda p, _entry, bn: PromptDetail(
            name=p.name,
            description=p.description or "",
            backend=bn,
            arguments=list(p.arguments) if p.arguments else [],
        ),
    )

    # Determine optimizer state for informational fields
    from argus_mcp.server.app import mcp_server as _mcp_server

    optimizer_active = getattr(_mcp_server, "optimizer_enabled", False)
    mcp_visible_tool_count = len(tools)
    if optimizer_active:
        from argus_mcp.bridge.optimizer.meta_tools import META_TOOLS

        keep_list = getattr(_mcp_server, "optimizer_keep_list", [])
        keep_names = set(keep_list)
        kept_count = sum(1 for t in service.tools if t.name in keep_names)
        mcp_visible_tool_count = len(META_TOOLS) + kept_count

    resp = CapabilitiesResponse(
        tools=tools,
        resources=resources,
        prompts=prompts,
        route_map=route_map,
        optimizer_active=optimizer_active,
        mcp_visible_tool_count=mcp_visible_tool_count,
    )
    return JSONResponse(resp.model_dump())


async def handle_events(request: Request) -> JSONResponse:
    """Recent events (polling)."""
    service = _get_service(request)

    try:
        limit = int(request.query_params.get("limit", "100"))
    except (ValueError, TypeError):
        return _error_json("bad_request", "'limit' must be an integer.", 400)
    if not MGMT_EVENTS_LIMIT_MIN <= limit <= MGMT_EVENTS_LIMIT_MAX:
        return _error_json(
            "bad_request",
            f"'limit' must be between {MGMT_EVENTS_LIMIT_MIN} and {MGMT_EVENTS_LIMIT_MAX}.",
            400,
        )
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


async def handle_events_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events stream for real-time event delivery."""
    service = _get_service(request)

    async def event_generator():
        queue = service.subscribe()
        try:
            # Send initial heartbeat
            yield _sse_format("heartbeat", {"message": "connected"}, "hb-0")

            while True:  # nosemgrep: mcp-unbounded-tool-loop
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


async def handle_reload(request: Request) -> JSONResponse:
    """Hot-reload config and reconnect changed backends."""
    service = _get_service(request)

    if not service.is_running:
        return _error_json("service_unavailable", "Service is not running.", 503)

    result = await service.reload()
    resp = ReloadResponse(**result)
    return JSONResponse(resp.model_dump())


async def handle_reconnect(request: Request) -> JSONResponse:
    """Reconnect a specific backend by name."""
    service = _get_service(request)
    name = request.path_params.get("name", "")

    if not name:
        return _error_json("bad_request", "Backend name is required.", 400)
    if len(name) > MGMT_BACKEND_NAME_MAX_LEN:
        return _error_json("bad_request", "Backend name is too long.", 400)
    if not _BACKEND_NAME_RE.match(name):
        return _error_json("bad_request", "Backend name contains invalid characters.", 400)

    if not service.is_running:
        return _error_json("service_unavailable", "Service is not running.", 503)

    # Check if backend exists
    if service.config_data and name not in service.config_data:
        return _error_json("not_found", f"Backend '{name}' not found.", 404)

    result = await service.reconnect_backend(name)
    resp = ReconnectResponse(**result)
    status_code = 200 if resp.reconnected else 500
    return JSONResponse(resp.model_dump(), status_code=status_code)


async def handle_reauth(request: Request) -> JSONResponse:
    """Trigger interactive re-authentication for a backend."""
    service = _get_service(request)
    name = request.path_params.get("name", "")

    if not name:
        return _error_json("bad_request", "Backend name is required.", 400)
    if len(name) > MGMT_BACKEND_NAME_MAX_LEN:
        return _error_json("bad_request", "Backend name is too long.", 400)
    if not _BACKEND_NAME_RE.match(name):
        return _error_json("bad_request", "Backend name contains invalid characters.", 400)

    if not service.is_running:
        return _error_json("service_unavailable", "Service is not running.", 503)

    if service.config_data and name not in service.config_data:
        return _error_json("not_found", f"Backend '{name}' not found.", 404)

    result = await service.reauth_backend(name)
    resp = ReAuthResponse(**result)
    status_code = 200 if resp.reauth_initiated else 500
    return JSONResponse(resp.model_dump(), status_code=status_code)


async def handle_shutdown(request: Request) -> JSONResponse:
    """Graceful server shutdown with backend cleanup."""
    service = _get_service(request)

    # Parse optional timeout from request body
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):  # noqa: E501
        body = {}

    try:
        req = ShutdownRequest(**body) if isinstance(body, dict) else ShutdownRequest()
    except (ValueError, TypeError):
        return _error_json("bad_request", "Invalid shutdown request body.", 400)

    timeout = req.timeout_seconds
    if not MGMT_SHUTDOWN_TIMEOUT_MIN <= timeout <= MGMT_SHUTDOWN_TIMEOUT_MAX:
        return _error_json(
            "bad_request",
            f"'timeout_seconds' must be between {MGMT_SHUTDOWN_TIMEOUT_MIN} and {MGMT_SHUTDOWN_TIMEOUT_MAX}.",
            400,
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


management_routes = Router(
    routes=[
        Route("/health", endpoint=handle_health, methods=["GET"]),
        Route("/ready", endpoint=handle_ready, methods=["GET"]),
        Route("/status", endpoint=handle_status, methods=["GET"]),
        Route("/backends", endpoint=handle_backends, methods=["GET"]),
        Route("/groups", endpoint=handle_groups, methods=["GET"]),
        Route("/capabilities", endpoint=handle_capabilities, methods=["GET"]),
        Route("/sessions", endpoint=handle_sessions, methods=["GET"]),
        Route("/events", endpoint=handle_events, methods=["GET"]),
        Route("/events/stream", endpoint=handle_events_stream, methods=["GET"]),
        Route("/reload", endpoint=handle_reload, methods=["POST"]),
        Route("/reconnect/{name}", endpoint=handle_reconnect, methods=["POST"]),
        Route("/reauth/{name}", endpoint=handle_reauth, methods=["POST"]),
        Route("/shutdown", endpoint=handle_shutdown, methods=["POST"]),
    ]
)
