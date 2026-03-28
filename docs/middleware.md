# Middleware Pipeline

Argus MCP processes every MCP request through a composable middleware
chain. Each middleware wraps the next, forming an onion-style pipeline
that handles cross-cutting concerns (auth, audit, telemetry, error
recovery) without coupling them to business logic.

## Chain Architecture

The actual chain is assembled in `_build_middleware_stack()` during server
startup. Conditional middlewares are included only when their feature is
configured.

```
     Client Request
           │
           ▼
┌──────────────────────┐
│  AuthMiddleware      │  ◄── Validates tokens, injects UserIdentity (conditional)
├──────────────────────┤
│  RecoveryMiddleware  │  ◄── Exception safety net (always)
├──────────────────────┤
│  PluginMiddleware    │  ◄── Pre/post plugin hooks (conditional)
├──────────────────────┤
│  TelemetryMiddleware │  ◄── OTel spans + metrics (conditional)
├──────────────────────┤
│  AuditMiddleware     │  ◄── Structured audit logging (always)
├──────────────────────┤
│  RoutingMiddleware   │  ◄── Resolve capability → backend, forward (terminal)
└──────────────────────┘
           │
           ▼
    Backend MCP Server
```

**Execution order:** outermost-first for requests, innermost-first for
responses. The first middleware in the list wraps all others.

> **Note:** `AuthzMiddleware` is implemented (`argus_mcp.bridge.middleware.authz`)
> but is **not currently wired** into the default chain built by
> `_build_middleware_stack()`. It can be added manually via `build_chain()`.

## Request Context

Every request carries a `RequestContext` dataclass through the chain:

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | `str` | Unique ID (uuid4 hex, 12 chars) |
| `capability_name` | `str` | Exposed capability name |
| `mcp_method` | `str` | `call_tool`, `read_resource`, or `get_prompt` |
| `arguments` | `dict` | Call arguments (optional) |
| `server_name` | `str` | Backend name (set by routing) |
| `original_name` | `str` | Original capability name at backend (set by routing) |
| `start_time` | `float` | Monotonic timestamp |
| `metadata` | `dict` | Arbitrary key-value store for middleware data |
| `error` | `Exception` | Set by recovery middleware on failure |

The `elapsed_ms` property computes wall-clock time since `start_time`.

## Middleware Reference

### AuthMiddleware

**Module:** `argus_mcp.bridge.middleware.auth`

Extracts the bearer token from `ctx.metadata["auth_token"]`, validates it
via the configured `AuthProviderRegistry`, and injects the resulting
`UserIdentity` into `ctx.metadata["user"]`.

- Raises `AuthenticationError` (401) on invalid tokens
- In anonymous mode, injects a no-op anonymous identity
- Skipped entirely when incoming auth is not configured

### RecoveryMiddleware

**Module:** `argus_mcp.bridge.middleware.recovery`

Exception safety net that catches any unhandled error and returns a
structured MCP error response so clients always get a well-formed reply.

- Sets `ctx.error` with the caught exception
- Returns `CallToolResult(isError=True)` with a sanitized message
- **Never leaks** internal details (file paths, SQL, stack traces)
- Falls back to JSON-RPC error format if MCP types are unavailable

### PluginMiddleware

**Module:** `argus_mcp.plugins`

Runs pre- and post-processing hooks from loaded plugins. Only added to
the chain when `plugins.enabled` is `true` and at least one plugin entry
is configured.

- Invokes `plugin_manager.pre_process()` before forwarding
- Invokes `plugin_manager.post_process()` after receiving a result
- Bypassed entirely when no plugins are configured

### TelemetryMiddleware

**Module:** `argus_mcp.bridge.middleware.telemetry`

Creates an OpenTelemetry trace span per request and records request metrics
(count, duration, error rate) via `record_request()`.

- Span name format: `mcp.<method>.<capability>`
- Attributes: `mcp.method`, `mcp.capability`, `mcp.request_id`, `mcp.backend`
- Records exceptions on the span
- Pass-through when OpenTelemetry is not installed

### AuditMiddleware

**Module:** `argus_mcp.bridge.middleware.audit`

Logs structured audit events for every request (pre and post). When an
`AuditLogger` is provided, events are written as JSON lines to a dedicated
audit file. Otherwise falls back to standard Python logging.

- Emits `AuditEvent` with source, target, outcome, and timing
- Events are NIST SP 800-53 AU-3 aligned
- See [Audit & Observability](audit/) for the event format

### RoutingMiddleware

**Module:** `argus_mcp.bridge.middleware.routing`

The innermost (terminal) middleware. Resolves the capability name to a
backend server via the `CapabilityRegistry`, then forwards the request
to the backend's MCP session.

- Populates `ctx.server_name` and `ctx.original_name`
- Validates `mcp_method` against allowed set: `call_tool`, `read_resource`, `get_prompt`
- Raises `ValueError` for unknown capabilities
- Raises `RuntimeError` for missing backend sessions

## Chain Construction

The chain is built during server startup in `_build_middleware_stack()`:

```python
from argus_mcp.bridge.middleware.chain import build_chain

# Minimal chain (auth disabled, no plugins, no telemetry)
chain = build_chain(
    middlewares=[RecoveryMiddleware(), AuditMiddleware(audit_logger)],
    handler=RoutingMiddleware(registry, manager),
)

# Full chain (auth + plugins + telemetry enabled)
chain = build_chain(
    middlewares=[
        AuthMiddleware(auth_registry),
        RecoveryMiddleware(),
        PluginMiddleware(plugin_manager),
        TelemetryMiddleware(),
        AuditMiddleware(audit_logger),
    ],
    handler=RoutingMiddleware(registry, manager),
)
```

The `build_chain()` function composes middlewares in list order: the first
middleware is the outermost wrapper. Each middleware calls `next_handler(ctx)`
to proceed down the chain.

## Writing Custom Middleware

A middleware is any async callable matching the `MCPMiddleware` protocol:

```python
from argus_mcp.bridge.middleware.chain import MCPHandler, RequestContext

class MyMiddleware:
    async def __call__(self, ctx: RequestContext, next_handler: MCPHandler) -> Any:
        # Pre-processing
        print(f"Before: {ctx.capability_name}")

        # Call next middleware/handler
        result = await next_handler(ctx)

        # Post-processing
        print(f"After: {ctx.elapsed_ms:.1f}ms")

        return result
```

Add it to the chain by inserting it at the desired position in the
`middlewares` list passed to `build_chain()`.
