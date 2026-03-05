# API Endpoint Reference

All endpoints are relative to `/manage/v1/`.

---

## `GET /health`

Liveness and readiness probe. **Always public** — no token required.

### Response

```json
{
  "status": "healthy",
  "uptime_seconds": 3600.5,
  "version": "0.7.0",
  "backends": {
    "total": 3,
    "connected": 3,
    "healthy": 2
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"healthy"`, `"degraded"`, or `"unhealthy"` |
| `uptime_seconds` | float | Seconds since server start |
| `version` | string | Server version |
| `backends.total` | int | Total configured backends |
| `backends.connected` | int | Currently connected backends |
| `backends.healthy` | int | Backends passing health checks |

**Status logic:**
- `healthy` — all backends connected and healthy
- `degraded` — some backends unhealthy or disconnected
- `unhealthy` — no backends connected

---

## `GET /status`

Full service status including config and transport info.

### Response

```json
{
  "service": {
    "name": "Argus MCP",
    "version": "0.7.0",
    "state": "running",
    "uptime_seconds": 3600.5,
    "started_at": "2026-02-23T12:00:00Z"
  },
  "config": {
    "file_path": "/path/to/config.yaml",
    "loaded_at": "2026-02-23T12:00:00Z",
    "backend_count": 3
  },
  "transport": {
    "sse_url": "http://127.0.0.1:9000/sse",
    "streamable_http_url": "http://127.0.0.1:9000/mcp",
    "host": "127.0.0.1",
    "port": 9000
  },
  "feature_flags": {
    "optimizer": false,
    "hot_reload": true,
    "outgoing_auth": true,
    "session_management": true,
    "yaml_config": true
  }
}
```

---

## `GET /backends`

List all backend connections with state, health, and capabilities.

### Response

```json
{
  "backends": [
    {
      "name": "my-server",
      "type": "stdio",
      "group": "default",
      "phase": "Ready",
      "state": "connected",
      "error": null,
      "capabilities": {
        "tools": 5,
        "resources": 2,
        "prompts": 1
      },
      "health": {
        "status": "healthy",
        "last_check": null,
        "latency_ms": null
      },
      "conditions": [
        {
          "type": "Ready",
          "status": true,
          "reason": "Connected",
          "message": "Backend initialized successfully",
          "last_transition": "2026-02-23T12:00:00Z"
        }
      ],
      "labels": {}
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Backend identifier (from config key) |
| `type` | string | `"stdio"`, `"sse"`, or `"streamable-http"` |
| `group` | string | Logical server group |
| `phase` | string | Lifecycle phase (see below) |
| `state` | string | Connection state |
| `error` | string? | Error message if failed |
| `capabilities` | object | Capability counts |
| `health` | object | Health check (`status`, `last_check`, `latency_ms`) |
| `conditions` | array | Structured conditions |

**Lifecycle phases:** `Pending`, `Initializing`, `Ready`, `Degraded`, `Failed`,
`ShuttingDown`

---

## `GET /groups`

List logical server groups and their members.

### Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `group` | string | Filter by group name (optional) |

### Response

```json
{
  "groups": {
    "default": {
      "servers": ["server-a", "server-b"],
      "count": 2
    },
    "search-tools": {
      "servers": ["search-server"],
      "count": 1
    }
  },
  "total_groups": 2,
  "total_servers": 3
}
```

---

## `GET /capabilities`

Aggregated tools, resources, and prompts from all connected backends.

### Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `type` | string | Filter by type: `tools`, `resources`, `prompts` |
| `backend` | string | Filter by backend name |
| `search` | string | Search capability names |

### Response

```json
{
  "tools": [
    {
      "name": "search_web",
      "original_name": "search_web",
      "description": "Search the web",
      "backend": "browser-server",
      "input_schema": { ... },
      "filtered": false,
      "renamed": false
    }
  ],
  "resources": [
    {
      "uri": "docs://readme",
      "name": "docs://readme",
      "backend": "docs-server",
      "mime_type": "text/markdown"
    }
  ],
  "prompts": [
    {
      "name": "code_review",
      "description": "Review code changes",
      "backend": "review-server",
      "arguments": [ ... ]
    }
  ],
  "route_map": {
    "search_web": ["browser-server", "search_web"],
    "docs://readme": ["docs-server", "docs://readme"]
  }
}
```

---

## `GET /sessions`

List active MCP client sessions.

### Response

```json
{
  "active_sessions": 2,
  "sessions": [
    {
      "id": "abc123",
      "transport_type": "sse",
      "tool_count": 15,
      "capability_snapshot": { "tools": 15, "resources": 3, "prompts": 2 },
      "age_seconds": 120.5,
      "idle_seconds": 10.2,
      "ttl": 3600,
      "expired": false
    }
  ]
}
```

---

## `GET /events`

Recent events (polling-based).

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 100 | Maximum events to return |
| `since` | ISO string | — | Return events after this timestamp |
| `severity` | string | — | Filter by severity level |

### Response

```json
{
  "events": [
    {
      "id": "evt_abc123",
      "timestamp": "2026-02-23T12:01:00Z",
      "stage": "connected",
      "message": "Backend 'my-server' connected successfully",
      "severity": "info",
      "backend": "my-server",
      "details": {}
    }
  ]
}
```

---

## `GET /events/stream`

Real-time event stream via Server-Sent Events (SSE).

### Usage

```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:9000/manage/v1/events/stream
```

Events are sent as SSE `data:` frames (JSON). A heartbeat comment is sent every
30 seconds to keep the connection alive.

```
data: {"id": "evt_abc", "timestamp": "...", "stage": "connected", ...}

data: {"id": "evt_def", "timestamp": "...", "stage": "error", ...}

: heartbeat
```

---

## `POST /reload`

Hot-reload the configuration file. Detects changes and reconnects affected
backends.

Requires `feature_flags.hot_reload: true` in config.

### Response

```json
{
  "reloaded": true,
  "backends_added": ["new-server"],
  "backends_removed": ["old-server"],
  "backends_changed": ["modified-server"],
  "errors": []
}
```

---

## `POST /reconnect/{name}`

Reconnect a specific backend by name.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `name` | string | Backend name (from config) |

### Response

```json
{
  "name": "my-server",
  "reconnected": true,
  "error": null
}
```

Returns 404 if the backend name is not found.

---

## `POST /shutdown`

Initiate graceful server shutdown.

### Request Body (optional)

```json
{
  "timeout_seconds": 30
}
```

### Response

```json
{
  "shutting_down": true
}
```

The server will:
1. Stop accepting new connections
2. Complete in-flight requests
3. Disconnect all backends
4. Exit the process
