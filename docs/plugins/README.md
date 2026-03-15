# Plugin System

Argus MCP includes a composable plugin framework that intercepts MCP
requests at well-defined hook points. Plugins run inside the middleware
chain — after recovery and before telemetry — so every request passes
through enabled plugins in priority order.

## How Plugins Work

Each plugin extends `PluginBase` and implements one or more async hooks.
The `PluginManager` runs hooks in **priority order** (lower number = runs
first), enforces per-plugin timeouts, and applies optional conditions.

```
PluginManager.run_hook("tool_pre_invoke", context)

  ┌────────────────────────────────────────────────┐
  │  For each enabled plugin (sorted by priority)  │
  │    1. Evaluate conditions (method, backend)    │
  │    2. Copy context (copy-on-write)             │
  │    3. Run hook with asyncio.timeout            │
  │    4. Apply execution_mode on error            │
  └────────────────────────────────────────────────┘
```

### Hook Points

Plugins receive context at eight points during request processing:

| Hook | When | Typical Use |
|------|------|-------------|
| `tool_pre_invoke` | Before a tool call is sent to the backend | Input validation, rate limiting, caching |
| `tool_post_invoke` | After a tool call returns | Output scanning, length guards, response caching |
| `prompt_pre_fetch` | Before a prompt is fetched | Access control, argument sanitization |
| `prompt_post_fetch` | After a prompt returns | Content filtering, PII scrubbing |
| `resource_pre_fetch` | Before a resource is read | URI validation, rate limiting |
| `resource_post_fetch` | After a resource returns | Secret detection, content moderation |
| `on_load` | When the plugin is first initialized | Setup, external connections |
| `on_unload` | When the plugin is torn down | Cleanup, flush buffers |

### Execution Modes

Each plugin has an `execution_mode` that controls what happens on failure:

| Mode | Behavior |
|------|----------|
| `enforce` | Plugin failure blocks the request (error returned to client) |
| `enforce_ignore_error` | Plugin failure is logged but the request continues **(default)** |
| `permissive` | Plugin runs best-effort; errors are silently ignored |
| `disabled` | Plugin is skipped entirely |

### Conditions

Plugins can be scoped to specific methods or backends:

```yaml
plugins:
  entries:
    - name: rate_limiter
      conditions:
        methods: ["call_tool"]           # Only tool calls
        backends: ["expensive-backend"]  # Only this backend
```

## Configuration

Plugins are configured under the `plugins` top-level key:

```yaml
plugins:
  enabled: true
  entries:
    - name: secrets_detection
      enabled: true
      execution_mode: enforce
      priority: 10
      timeout: 5.0
      settings:
        block: true

    - name: rate_limiter
      enabled: true
      priority: 50
      settings:
        max_requests: 100
        window: 60
```

### Plugin Config Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (required) | Plugin identifier |
| `enabled` | boolean | `true` | Whether the plugin is active |
| `execution_mode` | string | `"enforce_ignore_error"` | Error handling mode |
| `priority` | integer | `100` | Execution order (0–10000, lower runs first) |
| `timeout` | float | `30.0` | Per-invocation timeout in seconds (0.1–300.0) |
| `conditions` | object | `null` | Optional method/backend filters |
| `settings` | object | `{}` | Plugin-specific configuration |

### Top-Level Plugin Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `plugins.enabled` | boolean | `true` | Global plugin system toggle |
| `plugins.entries` | list | `[]` | List of plugin configurations |

## Middleware Chain Position

The `PluginMiddleware` sits in the middleware chain between Recovery and
Telemetry:

```
Auth → Recovery → PluginMiddleware → Telemetry → Audit → Routing
```

This means plugins run after crash protection (Recovery catches exceptions
from plugins too) and before observability (Telemetry records timing
including plugin overhead).

## Next Steps

- [Builtin Plugins](builtin-plugins.md) — 8 ready-to-use plugins
- [External & Custom Plugins](custom-plugins.md) — 7 integration plugins and authoring guide
- [Plugin Architecture](../architecture/05-plugins.md) — Internals deep-dive
