"""Management API router.

All routes are mounted under ``/manage/v1/`` by ``server/app.py``.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional, cast
from urllib.parse import urlunparse

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, Router

from argus_mcp._task_utils import _log_task_exception
from argus_mcp.constants import (
    MGMT_BACKEND_NAME_MAX_LEN,
    MGMT_EVENTS_LIMIT_MAX,
    MGMT_EVENTS_LIMIT_MIN,
    MGMT_QUERY_PARAM_MAX_LEN,
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
    BatchResponse,
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
    RegistrySearchResponse,
    RegistryServerEntry,
    ReloadResponse,
    ResourceDetail,
    SessionDetail,
    SessionsResponse,
    ShutdownRequest,
    ShutdownResponse,
    SkillActionResponse,
    SkillDetail,
    SkillsListResponse,
    StatusConfig,
    StatusResponse,
    StatusService,
    StatusTransport,
    ToolDetail,
)

logger = logging.getLogger(__name__)


_BACKEND_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

_SAFE_QUERY_RE = re.compile(r"^[a-zA-Z0-9_\-\.\s/\*]+$")


def _get_service(request: Request) -> ArgusService:
    """Retrieve the ArgusService instance from app state."""
    service: Optional[ArgusService] = getattr(request.app.state, "argus_service", None)
    if service is None:
        raise RuntimeError("ArgusService not found on app.state")
    return service


def _redact_status_response(status: Dict[str, Any]) -> Dict[str, Any]:
    """Strip sensitive internal details from a status response dict.

    Removes config file paths, transport bind addresses/URLs, and other
    implementation details that could aid reconnaissance (SEC-17).

    Safe to expose: service name, version, state, uptime, backend count,
    feature flags.
    """
    result = {**status}

    # Redact config file path
    if "config" in result:
        cfg = {**result["config"]}
        cfg["file_path"] = "[redacted]"
        result["config"] = cfg

    # Redact transport details (bind host/port, internal URLs)
    if "transport" in result:
        transport = {**result["transport"]}
        transport["host"] = "[redacted]"
        transport["port"] = 0
        transport["sse_url"] = "[redacted]"
        if "streamable_http_url" in transport:
            transport["streamable_http_url"] = "[redacted]"
        result["transport"] = transport

    return result


def _redact_backends_response(backends: Dict[str, Any]) -> Dict[str, Any]:
    """Strip sensitive internal details from a backends response dict.

    Removes error messages (may contain stack traces, IPs, credentials)
    and status conditions (may contain internal diagnostics) (SEC-17).

    Safe to expose: backend name, type, group, connection state,
    health status, capability counts.
    """
    result = {**backends}

    if "backends" in result:
        redacted_backends = []
        for backend in result["backends"]:
            b = {**backend}
            # Error messages may leak internal IPs, stack traces, credentials
            b["error"] = None
            # Conditions may contain detailed internal diagnostics
            b["conditions"] = []
            redacted_backends.append(b)
        result["backends"] = redacted_backends

    return result


def _error_json(error: str, message: str, status_code: int = 500) -> JSONResponse:
    body = ErrorResponse(error=error, message=message)
    return JSONResponse(body.model_dump(), status_code=status_code)


def _get_feature_flags() -> Dict[str, bool]:
    """Return feature flags from the mcp_server instance, or empty dict."""
    from argus_mcp.server.app import mcp_server
    from argus_mcp.server.state import get_state

    ff = get_state(mcp_server).feature_flags
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
    resp = _build_status(request)
    data = resp.model_dump()

    # Apply redaction when SecurityConfig.redact_status is enabled (SEC-17)
    if getattr(getattr(request.app.state, "security_config", None), "redact_status", False):
        data = _redact_status_response(data)

    return JSONResponse(data)


def _build_status(request: Request) -> StatusResponse:
    """Build the :class:`StatusResponse` — shared by ``/status`` and ``/batch``."""
    service = _get_service(request)
    svc_status = service.get_status()

    # host/port are set during server startup from CLI args (not user request data)
    host = getattr(request.app.state, "host", "127.0.0.1")  # nosec: not user-controlled
    port = getattr(request.app.state, "port", 0)  # nosec: not user-controlled
    sse_url = urlunparse(("http", f"{host}:{port}", SSE_PATH, "", "", ""))
    streamable_http_url = urlunparse(("http", f"{host}:{port}", STREAMABLE_HTTP_PATH, "", "", ""))

    return StatusResponse(
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


async def handle_backends(request: Request) -> JSONResponse:
    """List all backend server connections with their status."""
    resp = _build_backends(request)
    data = resp.model_dump()

    # Apply redaction when SecurityConfig.redact_status is enabled (SEC-17)
    if getattr(getattr(request.app.state, "security_config", None), "redact_status", False):
        data = _redact_backends_response(data)

    return JSONResponse(data)


def _build_backends(request: Request) -> BackendsResponse:
    """Build the :class:`BackendsResponse` — shared by ``/backends`` and ``/batch``."""
    service = _get_service(request)
    route_map = service.registry.get_route_map()

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

            gm = cast(GroupManager, service.group_manager)
            group_name = gm.group_of(bi.name)

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
    return resp


async def handle_groups(request: Request) -> JSONResponse:
    """List all server groups and their members.

    Query parameters:
        group (str): Filter to a specific group name.
    """
    service = _get_service(request)
    filter_group = request.query_params.get("group")

    if filter_group:
        if len(filter_group) > MGMT_QUERY_PARAM_MAX_LEN:
            return _error_json("bad_request", "Group name is too long.", 400)
        if not _SAFE_QUERY_RE.match(filter_group):
            return _error_json("bad_request", "Group name contains invalid characters.", 400)

    if service.group_manager is None:
        return JSONResponse({"groups": {}, "total_groups": 0, "total_servers": 0})

    from argus_mcp.bridge.groups import GroupManager

    gm = cast(GroupManager, service.group_manager)

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

    # Query parameters with validation
    filter_type = request.query_params.get("type")
    filter_backend = request.query_params.get("backend")
    filter_search = request.query_params.get("search", "").lower()

    for param_name, param_val in [
        ("type", filter_type),
        ("backend", filter_backend),
        ("search", filter_search),
    ]:
        if param_val is not None and len(param_val) > MGMT_QUERY_PARAM_MAX_LEN:
            return _error_json("bad_request", f"Query parameter '{param_name}' is too long.", 400)
    if filter_backend and not _BACKEND_NAME_RE.match(filter_backend):
        return _error_json("bad_request", "Backend name contains invalid characters.", 400)
    if filter_type and filter_type not in ("tools", "resources", "prompts"):
        return _error_json("bad_request", "Type must be one of: tools, resources, prompts.", 400)

    resp = _build_capabilities(
        service,
        route_map,
        filter_type=filter_type,
        filter_backend=filter_backend,
        filter_search=filter_search,
    )
    return JSONResponse(resp.model_dump())


def _build_capabilities(
    service: ArgusService,
    route_map: Dict[str, Any],
    *,
    filter_type: Optional[str] = None,
    filter_backend: Optional[str] = None,
    filter_search: str = "",
) -> CapabilitiesResponse:
    """Build the :class:`CapabilitiesResponse` — shared by ``/capabilities`` and ``/batch``."""

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
    from argus_mcp.server.state import get_state

    _svr_state = get_state(_mcp_server)
    optimizer_active = _svr_state.optimizer_enabled
    mcp_visible_tool_count = len(tools)
    if optimizer_active:
        from argus_mcp.bridge.optimizer.meta_tools import META_TOOLS

        keep_list = _svr_state.optimizer_keep_list
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
    return resp


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

    resp = _build_events(service, limit=limit, since=since, severity=severity)
    return JSONResponse(resp.model_dump())


def _build_events(
    service: ArgusService,
    *,
    limit: int = 100,
    since: Optional[str] = None,
    severity: Optional[str] = None,
) -> EventsResponse:
    """Build the :class:`EventsResponse` — shared by ``/events`` and ``/batch``."""
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
    return EventsResponse(events=items)


async def handle_batch(request: Request) -> JSONResponse:
    """Combined status + backends + capabilities + events in one response.

    Eliminates the per-poll multi-request overhead — one RTT per cycle.
    Accepts an optional ``events_limit`` query parameter (default 20).
    """
    service = _get_service(request)
    route_map = service.registry.get_route_map()

    try:
        events_limit = int(request.query_params.get("events_limit", "20"))
    except (ValueError, TypeError):
        events_limit = 20
    events_limit = max(MGMT_EVENTS_LIMIT_MIN, min(events_limit, MGMT_EVENTS_LIMIT_MAX))

    status_resp = _build_status(request)
    backends_resp = _build_backends(request)
    caps_resp = _build_capabilities(service, route_map)
    events_resp = _build_events(service, limit=events_limit)

    resp = BatchResponse(
        status=status_resp,
        backends=backends_resp,
        capabilities=caps_resp,
        events=events_resp,
    )
    data = resp.model_dump()

    # Apply redaction to the batch sub-responses when enabled (SEC-17)
    if getattr(getattr(request.app.state, "security_config", None), "redact_status", False):
        if "status" in data:
            data["status"] = _redact_status_response(data["status"])
        if "backends" in data:
            data["backends"] = _redact_backends_response(data["backends"])

    return JSONResponse(data)


async def handle_events_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events stream for real-time event delivery."""
    service = _get_service(request)

    async def event_generator():
        queue = service.subscribe()
        try:
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
    from argus_mcp.server.app import mcp_server
    from argus_mcp.server.state import get_state

    get_state(mcp_server).track_task(task)
    return JSONResponse(resp.model_dump())


async def _deferred_shutdown(service: ArgusService, timeout: int) -> None:
    """Run shutdown after a brief delay so the HTTP response can be sent."""
    await asyncio.sleep(0.5)  # Allow response to flush
    await service.shutdown(timeout_seconds=timeout)


async def handle_sessions(request: Request) -> JSONResponse:
    """List active client sessions."""
    from argus_mcp.server.app import mcp_server
    from argus_mcp.server.state import get_state

    session_mgr = get_state(mcp_server).session_manager
    if session_mgr is None:
        return JSONResponse(SessionsResponse(active_sessions=0, sessions=[]).model_dump())

    raw_sessions = session_mgr.list_sessions()
    details = [SessionDetail(**s) for s in raw_sessions]
    resp = SessionsResponse(
        active_sessions=session_mgr.active_count,
        sessions=details,
    )
    return JSONResponse(resp.model_dump())


async def handle_registry_search(request: Request) -> JSONResponse:
    """Search external MCP server registries (Glama, Smithery, etc.)."""
    service = _get_service(request)

    q = request.query_params.get("q", "").strip()
    if not q:
        return _error_json("bad_request", "Query parameter 'q' is required.", 400)
    if len(q) > MGMT_QUERY_PARAM_MAX_LEN or not _SAFE_QUERY_RE.match(q):
        return _error_json("bad_request", "Invalid query parameter.", 400)

    limit_str = request.query_params.get("limit", "20")
    try:
        limit = max(1, min(int(limit_str), 100))
    except ValueError:
        limit = 20

    registry_name = request.query_params.get("registry", "").strip() or None

    # Read registries from the full config model if available,
    # falling back to the legacy config_data dict for compatibility.
    full_cfg = service.full_config
    if full_cfg is not None and hasattr(full_cfg, "registries") and full_cfg.registries:
        registries = [r.model_dump() for r in full_cfg.registries]
    else:
        config_data = service.config_data or {}
        registries = config_data.get("registries", [])
    if not isinstance(registries, list) or not registries:
        return _error_json("not_configured", "No registries configured.", 404)

    # Filter to requested registry if specified
    if registry_name:
        registries = [r for r in registries if r.get("name") == registry_name]
        if not registries:
            return _error_json("not_found", f"Registry '{registry_name}' not found.", 404)

    from argus_mcp.registry.client import RegistryClient

    all_servers: list[dict[str, Any]] = []
    used_registry = ""
    for reg in registries:
        reg_url = reg.get("url", "")
        reg_type = reg.get("type", "auto")
        if not reg_url:
            continue
        client = RegistryClient(base_url=reg_url, registry_type=reg_type)
        try:
            results = await client.search(query=q, limit=limit)
            for entry in results:
                all_servers.append(
                    RegistryServerEntry(
                        name=entry.name,
                        description=entry.description,
                        transport=entry.transport,
                        url=entry.url,
                        command=entry.command,
                        args=entry.args,
                        version=entry.version,
                        categories=entry.categories,
                    ).model_dump()
                )
            if results:
                used_registry = reg.get("name", reg_url)
        except Exception:
            logger.debug("Registry search failed for %s", reg_url, exc_info=True)
        finally:
            await client.close()
        if all_servers:
            break  # Use first registry that returns results

    resp = RegistrySearchResponse(
        servers=all_servers[:limit],
        registry=used_registry,
        total=len(all_servers),
    )
    return JSONResponse(resp.model_dump())


def _get_skill_manager():
    """Retrieve the SkillManager from the MCP server state."""
    from argus_mcp.server.app import mcp_server
    from argus_mcp.server.state import get_state

    return get_state(mcp_server).skill_manager


async def handle_skills_list(request: Request) -> JSONResponse:
    """List all discovered skills with status."""
    mgr = _get_skill_manager()
    if mgr is None:
        return _error_json("not_available", "Skill manager not initialized.", 503)

    mgr.discover()
    skills = mgr.list_skills()
    details = [
        SkillDetail(
            name=s.manifest.name,
            version=s.manifest.version,
            description=s.manifest.description,
            status=s.status.value,
            tools=len(s.manifest.tools),
            workflows=len(s.manifest.workflows),
            author=s.manifest.author,
        ).model_dump()
        for s in skills
    ]
    return JSONResponse(SkillsListResponse(skills=details).model_dump())


async def handle_skills_enable(request: Request) -> JSONResponse:
    """Enable a skill by name."""
    mgr = _get_skill_manager()
    if mgr is None:
        return _error_json("not_available", "Skill manager not initialized.", 503)

    name = request.path_params.get("name", "")
    if not name or not _BACKEND_NAME_RE.match(name):
        return _error_json("bad_request", "Invalid skill name.", 400)

    skill = mgr.get(name)
    if skill is None:
        return _error_json("not_found", f"Skill '{name}' not found.", 404)

    mgr.enable(name)
    resp = SkillActionResponse(name=name, action="enabled")
    return JSONResponse(resp.model_dump())


async def handle_skills_disable(request: Request) -> JSONResponse:
    """Disable a skill by name."""
    mgr = _get_skill_manager()
    if mgr is None:
        return _error_json("not_available", "Skill manager not initialized.", 503)

    name = request.path_params.get("name", "")
    if not name or not _BACKEND_NAME_RE.match(name):
        return _error_json("bad_request", "Invalid skill name.", 400)

    skill = mgr.get(name)
    if skill is None:
        return _error_json("not_found", f"Skill '{name}' not found.", 404)

    mgr.disable(name)
    resp = SkillActionResponse(name=name, action="disabled")
    return JSONResponse(resp.model_dump())


async def handle_tools_call(request: Request) -> JSONResponse:
    """Proxy an MCP tools/call request to the correct backend."""
    service = _get_service(request)

    try:
        body = await request.json()
    except Exception:
        return _error_json("bad_request", "Invalid JSON body.", 400)

    tool_name = body.get("tool", "").strip()
    if not tool_name:
        return _error_json("bad_request", "Field 'tool' is required.", 400)
    arguments = body.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error_json("bad_request", "'arguments' must be an object.", 400)

    route_info = service.registry.resolve_capability(tool_name)
    if not route_info:
        return _error_json("not_found", f"Tool '{tool_name}' not found.", 404)

    svr_name, orig_name = route_info
    session = service.manager.get_session(svr_name)
    if not session:
        return _error_json(
            "backend_unavailable",
            f"Backend '{svr_name}' session not available.",
            503,
        )

    try:
        result = await session.call_tool(name=orig_name, arguments=arguments)
    except Exception as exc:
        logger.warning("tools/call %s failed: %s", tool_name, exc, exc_info=True)
        return _error_json("call_failed", str(exc), 502)

    # Serialize MCP CallToolResult
    content_list = []
    for item in getattr(result, "content", []):
        content_list.append(
            {"type": getattr(item, "type", "text"), "text": getattr(item, "text", str(item))}
        )
    return JSONResponse(
        {
            "tool": tool_name,
            "backend": svr_name,
            "content": content_list,
            "isError": getattr(result, "isError", False),
        }
    )


async def handle_resources_read(request: Request) -> JSONResponse:
    """Proxy an MCP resources/read request to the correct backend."""
    service = _get_service(request)

    try:
        body = await request.json()
    except Exception:
        return _error_json("bad_request", "Invalid JSON body.", 400)

    uri = body.get("uri", "").strip()
    if not uri:
        return _error_json("bad_request", "Field 'uri' is required.", 400)

    route_info = service.registry.resolve_capability(uri)
    if not route_info:
        return _error_json("not_found", f"Resource '{uri}' not found.", 404)

    svr_name, orig_uri = route_info
    session = service.manager.get_session(svr_name)
    if not session:
        return _error_json(
            "backend_unavailable",
            f"Backend '{svr_name}' session not available.",
            503,
        )

    try:
        result = await session.read_resource(uri=orig_uri)
    except Exception as exc:
        logger.warning("resources/read %s failed: %s", uri, exc, exc_info=True)
        return _error_json("read_failed", str(exc), 502)

    # Serialize MCP ReadResourceResult
    contents_list = []
    for item in getattr(result, "contents", []):
        contents_list.append(
            {
                "uri": getattr(item, "uri", uri),
                "text": getattr(item, "text", str(item)),
                "mimeType": getattr(item, "mimeType", None),
            }
        )
    return JSONResponse(
        {
            "uri": uri,
            "backend": svr_name,
            "contents": contents_list,
        }
    )


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
        Route("/batch", endpoint=handle_batch, methods=["GET"]),
        Route("/reload", endpoint=handle_reload, methods=["POST"]),
        Route("/reconnect/{name}", endpoint=handle_reconnect, methods=["POST"]),
        Route("/reauth/{name}", endpoint=handle_reauth, methods=["POST"]),
        Route("/shutdown", endpoint=handle_shutdown, methods=["POST"]),
        Route("/registry/search", endpoint=handle_registry_search, methods=["GET"]),
        Route("/skills", endpoint=handle_skills_list, methods=["GET"]),
        Route("/skills/{name}/enable", endpoint=handle_skills_enable, methods=["POST"]),
        Route("/skills/{name}/disable", endpoint=handle_skills_disable, methods=["POST"]),
        Route("/tools/call", endpoint=handle_tools_call, methods=["POST"]),
        Route("/resources/read", endpoint=handle_resources_read, methods=["POST"]),
    ]
)
