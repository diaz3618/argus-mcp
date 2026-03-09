# Config Loading Pipeline

The configuration system supports multiple formats, environment variable
expansion, secret resolution, schema validation, and live hot-reload.

## Loading Process

```
Config file (YAML)
  → Parse (pyyaml)
    → Expand ${ENV_VAR} references
      → Detect format (legacy or v1)
        → Auto-migrate legacy → v1 if needed
          → Validate against ArgusConfig (Pydantic)
            → Resolve secret:name references
              → Ready for use
```

## Modules

| Module | Purpose |
|--------|---------|
| `config/loader.py` | File I/O, format detection, validation |
| `config/schema.py` | Top-level ArgusConfig Pydantic model |
| `config/schema_backends.py` | Backend config models (stdio, SSE, streamable-http) |
| `config/schema_client.py` | Client/TUI config models |
| `config/schema_registry.py` | Registry config models |
| `config/schema_security.py` | Auth, authz, secrets config models |
| `config/schema_server.py` | Server & management config models |
| `config/migration.py` | Legacy flat-dict → v1 migration |
| `config/diff.py` | Config change detection for hot-reload |
| `config/flags.py` | Feature flag management |
| `config/watcher.py` | File system watcher for auto-reload |
| `config/client_gen.py` | Generate client-side MCP config |

## Public API

```python
from argus_mcp.config import load_and_validate_config, load_argus_config

# Returns downstream dict format
backends_dict = load_and_validate_config("config.yaml")

# Returns full Pydantic model
config = load_argus_config("config.yaml")
```

## File Format

Only YAML config files (`.yaml`, `.yml`) are supported.

## Environment Variable Expansion

All string values in the config are scanned for `${VAR_NAME}` patterns.
Expansion is recursive — a variable can resolve to a string containing
another `${VAR}` reference.

```yaml
server:
  management:
    token: "${ARGUS_MGMT_TOKEN}"

backends:
  my-server:
    type: sse
    url: "http://${HOST}:${PORT}/sse"
```

## Hot-Reload

When `feature_flags.hot_reload` is enabled:

1. `POST /manage/v1/reload` triggers a config reload
2. `config/diff.py` compares old and new configs
3. Changed backends are reconnected
4. Added backends are started
5. Removed backends are stopped
6. Unchanged backends are left alone

The file system watcher is always active when a config path is available —
it monitors the config file for changes and triggers reloads automatically.
There is no separate feature flag for the watcher.

## Client Config Generation

`config/client_gen.py` generates MCP client configuration files (e.g., for
Claude Desktop) that point at the Argus gateway, simplifying client setup.
