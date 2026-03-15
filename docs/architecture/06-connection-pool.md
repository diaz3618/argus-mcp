# Connection Pool Architecture

Argus MCP manages backend connections through three cooperating
components: `SessionPool` for MCP stdio/SSE sessions, `HttpPool` for HTTP
keep-alive connections, and `RetryManager` for transient failure recovery.

## Components

```
┌───────────────────────────────────────────────────┐
│                  Bridge Layer                     │
│                                                   │
│  ┌───────────────┐  ┌───────────┐  ┌───────────┐  │
│  │  SessionPool  │  │  HttpPool │  │  Retry    │  │
│  │ (MCP sessions │  │  (httpx   │  │  Manager  │  │
│  │  per backend) │  │   pool)   │  │           │  │
│  └──────┬────────┘  └─────┬─────┘  └─────┬─────┘  │
│         │                 │              │        │
│         └─────────────────┴──────────────┘        │
│                           │                       │
│                  Backend Connections              │
└───────────────────────────────────────────────────┘
```

## SessionPool

Manages MCP client sessions (stdio and SSE transports). Each backend gets
its own pool of sessions up to `per_key_max`. Idle sessions are reaped
after their TTL expires.

### Configuration

```yaml
session_pool:
  per_key_max: 4
  ttl: 300
  reap_interval: 30
  cb_threshold: 3
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `per_key_max` | integer | `4` | Maximum concurrent sessions per backend |
| `ttl` | integer | `300` | Idle session TTL in seconds |
| `reap_interval` | integer | `30` | How often to check for expired sessions |
| `cb_threshold` | integer | `3` | Circuit breaker trip threshold per backend |

### Behavior

- **Acquisition**: Requests a session for a backend key. If a pooled idle
  session exists and hasn't expired, it is reused. Otherwise, a new
  session is created (up to `per_key_max`).
- **Release**: After use, the session is returned to the pool with a fresh
  TTL timestamp.
- **Reaping**: A background task runs every `reap_interval` seconds,
  closing sessions that have been idle longer than `ttl`.
- **Circuit breaker**: If a backend produces `cb_threshold` consecutive
  connection failures, the pool stops creating new sessions for that key
  until a cooldown elapses.

## HttpPool

Wraps `httpx.AsyncClient` with connection pooling for SSE and
streamable-HTTP backends that communicate over HTTP.

### Configuration

```yaml
http_pool:
  max_connections: 200
  max_keepalive: 100
  timeout: 30
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_connections` | integer | `200` | Total connection limit across all backends |
| `max_keepalive` | integer | `100` | Maximum idle keep-alive connections |
| `timeout` | integer | `30` | Default request timeout in seconds |

### Behavior

Uses `httpx.AsyncClient` with `limits=httpx.Limits(max_connections,
max_keepalive_connections)`. The pool is created once at startup and shared
across all HTTP-based backends. Individual request timeouts can still be
overridden per-backend in the `backends` config.

## RetryManager

Handles transient HTTP failures with exponential backoff, jitter, and a
configurable set of retryable status codes.

### Configuration

```yaml
retry:
  max_retries: 3
  base_delay: 1.0
  backoff_factor: 2.0
  max_delay: 60.0
  jitter: 0.5
  retryable_status_codes: [408, 429, 502, 503, 504]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_retries` | integer | `3` | Maximum retry attempts |
| `base_delay` | float | `1.0` | Initial delay in seconds |
| `backoff_factor` | float | `2.0` | Multiplier per retry |
| `max_delay` | float | `60.0` | Maximum delay cap in seconds |
| `jitter` | float | `0.5` | Random jitter factor (0–1) |
| `retryable_status_codes` | list[int] | `[408, 429, 502, 503, 504]` | HTTP codes that trigger retry |

### Retry Formula

```
delay = min(base_delay * backoff_factor^attempt, max_delay)
actual_delay = delay * (1 + random(-jitter, +jitter))
```

### Behavior

- Only retries on status codes in `retryable_status_codes` or on
  connection errors (timeout, connection refused).
- Each retry logs the attempt number, status code, and computed delay.
- After `max_retries` exhausted, the last error is re-raised to the
  caller.

## SSE Resilience

For SSE (Server-Sent Events) backends, additional reconnection settings
control how the client handles dropped connections:

```yaml
sse_resilience:
  reconnect_attempts: 5
  reconnect_delay: 2.0
  ping_interval: 30
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `reconnect_attempts` | integer | `5` | Max reconnection attempts on SSE drop |
| `reconnect_delay` | float | `2.0` | Delay between reconnection attempts |
| `ping_interval` | integer | `30` | Keep-alive ping interval in seconds |

## Integration with the Bridge

The session pool and HTTP pool are instantiated during server startup and
injected into the bridge layer. The bridge's `BackendManager` uses them
when routing requests:

```
1. Incoming request arrives at RoutingMiddleware
2. BackendManager resolves the target backend
3. SessionPool provides an MCP session (or HttpPool for HTTP calls)
4. RetryManager wraps the call for transient failure recovery
5. Response flows back through the middleware chain
```

All three components respect the backend's group assignment — the
`GroupManager` can route to a specific backend within a group, and the
pool/retry logic operates per-backend independently.
