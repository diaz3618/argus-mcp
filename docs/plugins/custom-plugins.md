# External & Custom Plugins

Beyond the builtin plugins, Argus MCP provides seven integration plugins
for external policy engines, scanners, and content moderation services.
You can also author your own plugins.

## External Plugins

### opa_policy

Evaluates tool requests against an Open Policy Agent instance. The plugin
sends the request context to the OPA decision endpoint and blocks
non-compliant calls.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `opa_url` | string | `"http://localhost:8181"` | OPA server URL |

```yaml
- name: opa_policy
  execution_mode: enforce
  priority: 5
  settings:
    opa_url: "http://localhost:8181"
```

### cedar_policy

Evaluates requests against an Amazon Cedar policy engine instance.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `cedar_url` | string | `"http://localhost:8180"` | Cedar server URL |

```yaml
- name: cedar_policy
  execution_mode: enforce
  priority: 5
  settings:
    cedar_url: "http://localhost:8180"
```

### clamav

Scans request/response payloads for malware using ClamAV.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `host` | string | `"127.0.0.1:3310"` | ClamAV daemon address |

```yaml
- name: clamav
  execution_mode: enforce
  priority: 8
  settings:
    host: "127.0.0.1:3310"
```

### virustotal

Checks content hashes against the VirusTotal database. The API key
should be stored in the encrypted secret store and referenced via the
`VT_API_KEY` environment variable.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `api_key` | string | (from `VT_API_KEY`) | VirusTotal API key |
| `threshold` | integer | `3` | Detection count to trigger blocking |

```yaml
- name: virustotal
  execution_mode: enforce
  priority: 8
  settings:
    threshold: 3
```

### llmguard

Sends prompts to an LLM Guard instance for injection and toxicity
detection.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `api_url` | string | `"http://localhost:8800"` | LLM Guard API URL |
| `threshold` | float | `0.5` | Score threshold for blocking |

```yaml
- name: llmguard
  execution_mode: enforce
  priority: 12
  settings:
    api_url: "http://localhost:8800"
    threshold: 0.5
```

### content_moderation

Routes content through a cloud moderation service. Supports multiple
provider backends.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `provider` | string | (required) | One of: `openai`, `azure`, `aws`, `granite`, `watson` |

```yaml
- name: content_moderation
  execution_mode: enforce
  priority: 12
  settings:
    provider: "openai"
```

### unified_pdp

Combines multiple policy decision engines (OPA, Cedar, custom) into a
single evaluation with configurable combination logic.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `engines` | list | (required) | List of engine configurations |
| `combination_mode` | string | `"all"` | How to combine results: `all`, `any`, `majority` |

```yaml
- name: unified_pdp
  execution_mode: enforce
  priority: 5
  settings:
    engines:
      - type: opa
        url: "http://localhost:8181"
      - type: cedar
        url: "http://localhost:8180"
    combination_mode: "all"
```

## Writing a Custom Plugin

Create a Python file that extends `PluginBase` and implement the hooks you
need. Place it somewhere importable or register it through the plugin
discovery mechanism.

### Minimal Example

```python
from argus_mcp.plugins.base import PluginBase


class MyPlugin(PluginBase):
    """Example plugin that logs every tool call."""

    name = "my_logger"

    async def tool_pre_invoke(self, context: dict) -> dict:
        tool_name = context.get("tool_name", "unknown")
        self.logger.info("Tool called: %s", tool_name)
        return context

    async def tool_post_invoke(self, context: dict) -> dict:
        self.logger.info("Tool completed: %s", context.get("tool_name"))
        return context
```

### Plugin Lifecycle

1. **on_load** — Called once when the plugin manager initializes the
   plugin. Use for setup (open connections, load config).
2. **Hook calls** — `tool_pre_invoke`, `tool_post_invoke`, etc. are called
   for each matching request. Context is copy-on-write: modifications to
   the dict are isolated to your plugin unless you return the modified
   context.
3. **on_unload** — Called during shutdown. Close connections and flush
   buffers here.

### Configuration Passthrough

Whatever you put under `settings:` in config.yaml is available as
`self.settings` inside the plugin:

```yaml
plugins:
  entries:
    - name: my_logger
      enabled: true
      priority: 50
      settings:
        log_level: "DEBUG"
        include_args: true
```

```python
async def on_load(self, context: dict) -> dict:
    level = self.settings.get("log_level", "INFO")
    self.logger.setLevel(level)
    return context
```

### Conditions

Use `conditions` to restrict when the plugin runs:

```yaml
- name: my_logger
  conditions:
    methods: ["call_tool"]
    backends: ["debug-server"]
```

The plugin will only execute for `call_tool` requests routed to
`debug-server`.
