# Plugin Architecture

This page covers the internals of the plugin subsystem: the manager, the
middleware layer, hook execution, and the copy-on-write context model.

## Package Layout

```
argus_mcp/plugins/
├── __init__.py          # Public exports
├── base.py              # PluginBase abstract class
├── config.py            # PluginConfig, PluginsConfig, PluginCondition
├── manager.py           # PluginManager (hook dispatch, lifecycle)
├── middleware.py         # PluginMiddleware (bridge middleware integration)
├── builtins/
│   ├── __init__.py
│   ├── secrets_detection.py
│   ├── pii_filter.py
│   ├── rate_limiter.py
│   ├── circuit_breaker.py
│   ├── retry_with_backoff.py
│   ├── response_cache_by_prompt.py
│   ├── output_length_guard.py
│   └── markdown_cleaner.py
└── external/
    ├── __init__.py
    ├── opa_policy.py
    ├── cedar_policy.py
    ├── clamav.py
    ├── virustotal.py
    ├── llmguard.py
    ├── content_moderation.py
    └── unified_pdp.py
```

## PluginBase

`PluginBase` defines the eight async hook methods. All hooks accept a
`context` dict and return a (possibly modified) dict. Default
implementations are no-ops that return the context unchanged.

```
class PluginBase:
    name: str              # Unique plugin identifier
    settings: dict         # From config.yaml entries[].settings
    logger: Logger         # Per-plugin logger

    async def tool_pre_invoke(ctx) -> ctx
    async def tool_post_invoke(ctx) -> ctx
    async def prompt_pre_fetch(ctx) -> ctx
    async def prompt_post_fetch(ctx) -> ctx
    async def resource_pre_fetch(ctx) -> ctx
    async def resource_post_fetch(ctx) -> ctx
    async def on_load(ctx) -> ctx
    async def on_unload(ctx) -> ctx
```

## PluginManager

The `PluginManager` owns the plugin lifecycle: instantiation from config,
hook dispatch, and shutdown.

### Initialization

```
PluginManager(plugins_config: PluginsConfig)
  for each entry in plugins_config.entries:
    if entry.enabled:
      instantiate plugin by name (builtin or external lookup)
      call plugin.on_load()
      register in priority-sorted list
```

### Hook Execution: run_hook()

```
run_hook(hook_name: str, context: dict) -> dict
  for plugin in sorted_plugins:          # by priority ascending
    if not plugin.enabled:
      continue
    if conditions and not conditions.match(context):
      continue
    ctx_copy = copy(context)             # copy-on-write isolation
    try:
      with asyncio.timeout(plugin.timeout):
        result = await plugin.<hook_name>(ctx_copy)
        context = result                 # adopt returned context
    except TimeoutError:
      handle per execution_mode
    except Exception:
      handle per execution_mode
  return context
```

### Execution Mode Handling

| Mode | On Error |
|------|----------|
| `enforce` | Re-raise → request fails |
| `enforce_ignore_error` | Log warning → continue with pre-plugin context |
| `permissive` | Silently continue |
| `disabled` | Plugin skipped entirely |

### Shutdown

```
async shutdown():
  for plugin in reversed(sorted_plugins):
    await plugin.on_unload()
```

## PluginMiddleware

`PluginMiddleware` bridges the plugin system into the standard middleware
chain. It implements the `MCPMiddleware` protocol.

### Chain Position

```
Auth → Recovery → PluginMiddleware → Telemetry → Audit → Routing
                  ^^^^^^^^^^^^^^^^
```

### Request Flow

```
async process(request, context, next_middleware):
  # Pre-hooks
  context = await manager.run_hook("tool_pre_invoke", context)
  # (or prompt_pre_fetch / resource_pre_fetch based on request type)

  response = await next_middleware(request, context)

  # Post-hooks
  context["response"] = response
  context = await manager.run_hook("tool_post_invoke", context)

  return context.get("response", response)
```

## Copy-on-Write Context

Each plugin receives a **shallow copy** of the context dict. This means:

- Plugins can freely add/modify keys without affecting other plugins
- The plugin's return value becomes the new context for the next plugin
- If a plugin fails, the pre-plugin context is preserved (in
  `enforce_ignore_error` and `permissive` modes)

This design prevents one misbehaving plugin from corrupting state for
others while still allowing intentional context enrichment (e.g., adding
metadata, modifying arguments).

## Condition Evaluation

`PluginCondition` supports two optional filters:

| Field | Type | Behavior |
|-------|------|----------|
| `methods` | list[str] | Only run for these MCP methods |
| `backends` | list[str] | Only run for requests routed to these backends |

Both filters use AND logic: if both are set, the request must match both.
If neither is set, the plugin runs for all requests.

## Rust Acceleration

Two builtin plugins have optional Rust implementations via PyO3:

- `RustSecretsScanner` — Pattern matching for secrets_detection
- `RustPiiFilter` — Regex-based PII detection

The Python implementations detect the native extensions at import time
and delegate automatically. If the Rust extension is not compiled, the
pure-Python fallback is used with no configuration change needed.
