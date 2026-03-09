# Configuration Reference

Argus MCP uses a structured configuration file to define backends,
authentication, middleware, and operational settings.

## File Format

Argus uses **YAML** config files. The loader auto-detects the extension.

| Extension | Format |
|-----------|--------|
| `.yaml`, `.yml` | YAML |

### Config File Resolution

Argus searches for config files in this order:

1. `--config` CLI flag (explicit path)
2. `ARGUS_CONFIG` environment variable
3. Auto-detect in project directory: `config.yaml` → `config.yml`

## Config Structure

```yaml
version: "1"                    # Config format version (required)

server: { ... }                 # Server settings
client: { ... }                 # TUI / client settings
backends: { ... }               # Backend MCP server definitions
conflict_resolution: { ... }    # Capability conflict strategy
audit: { ... }                  # Audit logging
optimizer: { ... }              # Tool optimizer (meta-tools)
telemetry: { ... }              # OpenTelemetry integration
secrets: { ... }                # Encrypted secret management
registries: [ ... ]             # External MCP server catalogs
incoming_auth: { ... }          # Incoming client authentication
authorization: { ... }          # RBAC policies
feature_flags: { ... }          # Feature toggles
```

## Variable Expansion

Config values support two types of dynamic references:

### Environment Variables

Use `${VAR_NAME}` to inject environment variable values:

```yaml
backends:
  my-server:
    type: sse
    url: "http://localhost:${MY_SERVER_PORT}/sse"
    headers:
      Authorization: "Bearer ${MY_API_KEY}"
```

### Secret References

Use `secret:<name>` to resolve values from the encrypted secret store:

```yaml
backends:
  my-server:
    type: sse
    url: "http://localhost:8080/sse"
    headers:
      Authorization: "Bearer secret:my-api-key"
```

See [Secrets Management](security/secrets.md) for setting up the secret store.

---

## `server`

Server listen address and transport settings.

```yaml
server:
  host: "127.0.0.1"
  port: 9000
  transport: sse                # "sse" or "streamable-http"
  management:
    enabled: true
    token: "${ARGUS_MGMT_TOKEN}"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"127.0.0.1"` | Bind address |
| `port` | integer | `9000` | Listen port (1–65535) |
| `transport` | string | `"sse"` | Primary transport: `"sse"` or `"streamable-http"` |
| `management.enabled` | boolean | `true` | Enable the `/manage/v1/` REST API |
| `management.token` | string | `null` | Bearer token for management endpoints. Also `ARGUS_MGMT_TOKEN` env var. If unset, management API has no auth. |

> **Note:** Both transports are always available regardless of the `transport`
> setting. The setting controls which is advertised as primary.

---

## `backends`

A map of named backend MCP server connections. Each backend has a `type` that
determines its connection method.

### Stdio Backend

Launches a local process and communicates via stdin/stdout.

```yaml
backends:
  my-local-tool:
    type: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-everything"]
    env:
      NODE_ENV: production
    group: tools
    timeouts:
      init: 30
    filters:
      tools:
        allow: ["search_*"]
        deny: ["dangerous_*"]
    tool_overrides:
      old_name:
        name: new_name
        description: "Custom description"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"stdio"` | — | **Required** |
| `command` | string | — | **Required.** Executable to launch |
| `args` | list[string] | `[]` | Command arguments |
| `env` | map | `null` | Environment variables for the process |
| `group` | string | `"default"` | Logical server group |
| `timeouts` | object | defaults | Connection timeouts |
| `filters` | object | defaults | Capability filters |
| `tool_overrides` | map | `{}` | Per-tool name/description overrides |

### Automatic Container Isolation

Argus automatically wraps every stdio backend in an isolated container
(Docker or Podman) when a supported runtime is detected on the host.
**No configuration is needed** — container isolation is transparent and
applied by default with secure settings:

- **Filesystem**: `--read-only` root filesystem + tmpfs for `/tmp` and `/home/nonroot`
- **Privileges**: `--cap-drop ALL`, `--security-opt no-new-privileges`
- **Resources**: `--memory 512m --cpus 1`
- **User**: UID 65532 (`nonroot`), matching distroless/Chainguard standards
- **Init**: `--init` for proper signal handling

#### Image Building Pipeline

Argus builds a purpose-built Docker image for each backend using Jinja2
templates. The command determines which template is used:

| Command | Template | Base Image |
|---------|----------|------------|
| `uvx`, `uv`, `python`, `python3` | `uvx.dockerfile.j2` | `python:3.13-slim` |
| `npx`, `node`, `tsx` | `npx.dockerfile.j2` | `node:22-alpine` |
| `go` | `go.dockerfile.j2` | `golang:1.24-alpine` |

Each template creates a non-root user (UID 65532), installs the required
packages, and sets `HOME=/home/nonroot` and `TMPDIR=/tmp`.

If no container runtime is available, or the command has no recognized
template mapping, Argus falls back to running the backend as a bare
subprocess (with a log warning).

#### Per-Backend Container Options

Individual backends can customize their container:

```yaml
backends:
  my-backend:
    type: stdio
    command: npx
    args: ["-y", "my-mcp-server"]
    container_isolation: true          # default: inherits global flag
    builder_image: "node:22-alpine"    # override base image
    system_deps: ["curl", "jq"]        # additional OS packages
    additional_packages: []            # extra language-level packages
```

#### Disabling Container Isolation

Globally via environment variable:

```bash
ARGUS_CONTAINER_ISOLATION=false
```

Or the feature flag in your config:

```yaml
feature_flags:
  container_isolation: false
```

Or per-backend:

```yaml
backends:
  my-backend:
    container_isolation: false
```

#### Pre-Building Images

By default Argus builds the container image automatically the first
time it encounters each backend. To pre-build all images ahead of time:

```bash
argus-mcp build --config config.yaml
```

To **skip the build** and fail fast if the image is absent:

```bash
ARGUS_CONTAINER_BUILD_IF_MISSING=false
```

This is useful in production deployments where images should be pre-built
and pushed to a registry, not built on demand.

### SSE Backend

Connects to a remote MCP server via Server-Sent Events.

```yaml
backends:
  remote-sse:
    type: sse
    url: "http://remote-host:8080/sse"
    headers:
      X-Custom: "value"
    auth:
      type: static
      headers:
        Authorization: "Bearer ${API_TOKEN}"
    group: remote
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"sse"` | — | **Required** |
| `url` | string | — | **Required.** SSE endpoint URL (must start with `http://` or `https://`) |
| `command` | string | `null` | Optional local process to launch before connecting |
| `args` | list[string] | `[]` | Process arguments |
| `env` | map | `null` | Process environment |
| `headers` | map | `null` | Extra HTTP headers (values support `${ENV_VAR}`) |
| `auth` | object | `null` | [Outgoing auth](security/outgoing-auth.md) config |
| `group` | string | `"default"` | Logical server group |
| `timeouts` | object | defaults | Connection timeouts |
| `filters` | object | defaults | Capability filters |
| `tool_overrides` | map | `{}` | Per-tool name/description overrides |

### Streamable HTTP Backend

Connects via the newer MCP Streamable HTTP transport.

```yaml
backends:
  remote-http:
    type: streamable-http
    url: "http://remote-host:8080/mcp"
    auth:
      type: oauth2
      token_url: "https://auth.example.com/token"
      client_id: "argus"
      client_secret: "${OAUTH_SECRET}"
      scopes: ["mcp:read", "mcp:write"]
```

Or using PKCE for browser-based login (see [outgoing auth docs](security/outgoing-auth.md)):

```yaml
backends:
  remote-http:
    type: streamable-http
    url: "https://mcp.example.com/mcp"
    auth:
      type: pkce
      authorization_endpoint: "https://auth.example.com/authorize"
      token_endpoint: "https://auth.example.com/token"
      client_id: "my-client"
      scopes: ["openid"]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `"streamable-http"` | — | **Required** |
| `url` | string | — | **Required.** HTTP endpoint URL |
| `headers` | map | `null` | Extra HTTP headers |
| `auth` | object | `null` | [Outgoing auth](security/outgoing-auth.md) config |
| `group` | string | `"default"` | Logical server group |
| `timeouts` | object | defaults | Connection timeouts |
| `filters` | object | defaults | Capability filters |
| `tool_overrides` | map | `{}` | Per-tool name/description overrides |

### Common Backend Options

#### Timeouts

```yaml
timeouts:
  init: 30        # MCP session initialization (seconds)
  cap_fetch: 10   # Capability list fetch (seconds)
  sse_startup: 5  # Wait for local SSE process to start (seconds)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `init` | float | `null` (use global default: 15s) | MCP session init timeout |
| `cap_fetch` | float | `null` (use global default: 10s) | Capability fetch timeout |
| `sse_startup` | float | `null` (use global default: 5s) | Local SSE process startup wait |

#### Filters

Glob-based allow/deny lists for capability names. Applied per capability type.
Deny takes precedence over allow.

```yaml
filters:
  tools:
    allow: ["search_*", "read_*"]
    deny: ["dangerous_tool"]
  resources:
    allow: ["*"]
  prompts:
    deny: ["internal_*"]
```

#### Tool Overrides

Rename or re-describe specific tools before they are exposed to clients:

```yaml
tool_overrides:
  original_tool_name:
    name: better_name
    description: "A clearer description of what this tool does"
```

### Startup Concurrency and Stagger

Argus limits how many backends initialize simultaneously to prevent resource
contention (npm/pip package cache lock fights, network saturation, CPU spikes
on cold starts).

| Constant | Default | Description |
|----------|---------|-------------|
| `STARTUP_CONCURRENCY` | `4` | Max simultaneous backend initializations |
| `STARTUP_STAGGER_DELAY` | `0.5 s` | Delay between launching each backend within a batch |

These are tunable via environment variables for deployments with many backends:

```bash
# Allow more parallel connections on a powerful host
ARGUS_STARTUP_CONCURRENCY=8 argus-mcp server

# Increase stagger to ease network pressure
ARGUS_STARTUP_STAGGER_DELAY=1.0 argus-mcp server
```

### Backend Retry

When a backend fails to initialize, Argus retries automatically with
exponential back-off:

| Constant | Default | Description |
|----------|---------|-------------|
| `BACKEND_RETRIES` | `3` | Number of retry attempts after initial failure |
| `BACKEND_RETRY_DELAY` | `5.0 s` | Base delay before first retry |
| `BACKEND_RETRY_BACKOFF` | `1.5 ×` | Multiplier applied to delay on each successive retry |

Example retry schedule (defaults): 5 s → 7.5 s → 11.25 s.

Tunable via environment variables:

```bash
ARGUS_BACKEND_RETRIES=5
ARGUS_BACKEND_RETRY_DELAY=10.0
ARGUS_BACKEND_RETRY_BACKOFF=2.0
```

---

## `conflict_resolution`

Strategy for handling duplicate capability names across backends.

```yaml
conflict_resolution:
  strategy: prefix        # first-wins | prefix | priority | error
  separator: "_"
  order: []
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy` | string | `"first-wins"` | Resolution strategy (see below) |
| `separator` | string | `"_"` | Separator for prefix strategy |
| `order` | list[string] | `[]` | Backend priority for `priority` strategy |

**Strategies:**

| Strategy | Behavior |
|----------|----------|
| `first-wins` | First backend to register a name wins; duplicates are dropped |
| `prefix` | Prefix capability with backend name: `backend_toolname` |
| `priority` | Use `order` list to determine winner; others are dropped |
| `error` | Raise `CapabilityConflictError` at startup |

---

## `audit`

Structured audit logging (NIST SP 800-53 AU-3 aligned).

```yaml
audit:
  enabled: true
  file: "logs/audit.jsonl"
  max_size_mb: 100
  backup_count: 5
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable audit event logging |
| `file` | string | `"logs/audit.jsonl"` | Path to JSONL audit log |
| `max_size_mb` | integer | `100` | Max file size before rotation (≥1) |
| `backup_count` | integer | `5` | Number of rotated backups (≥0) |

See [Audit & Observability](audit/) for event format and details.

---

## `optimizer`

Replaces the full tool catalog with two meta-tools (`find_tool` and `call_tool`)
for LLMs that struggle with large tool lists.

```yaml
optimizer:
  enabled: false
  keep_tools:
    - important_tool
    - another_tool
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable the tool optimizer |
| `keep_tools` | list[string] | `[]` | Tools to always expose alongside meta-tools |

When enabled, clients see only `find_tool`, `call_tool`, and any `keep_tools`.
The LLM uses `find_tool` to search the tool index, then `call_tool` to invoke
the selected tool.

---

## `telemetry`

OpenTelemetry integration for distributed tracing and metrics.

```yaml
telemetry:
  enabled: false
  otlp_endpoint: "http://localhost:4317"
  service_name: "argus-mcp"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable OpenTelemetry tracing and metrics |
| `otlp_endpoint` | string | `"http://localhost:4317"` | OTLP collector endpoint (gRPC or HTTP) |
| `service_name` | string | `"argus-mcp"` | Service name reported to the collector |

When enabled, a `TelemetryMiddleware` is inserted into the middleware chain
and spans are exported to the configured OTLP endpoint. Requires the
`opentelemetry-*` packages to be installed.

---

## `secrets`

Automatic secret resolution for config values.

```yaml
secrets:
  enabled: false
  provider: "env"
  path: ""
  strict: false
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable automatic secret resolution |
| `provider` | string | `"env"` | Provider type: `"env"`, `"file"`, or `"keyring"` |
| `path` | string | `""` | Path for the file provider (ignored for other providers) |
| `strict` | boolean | `false` | Raise an error if a referenced secret cannot be resolved |

When enabled, `secret:<name>` references in config values are resolved
before Pydantic validation. See [Secrets Management](security/secrets.md)
for provider details.

---

## `incoming_auth`

Authentication for incoming MCP client connections.

```yaml
incoming_auth:
  type: jwt                              # anonymous | local | jwt | oidc
  jwks_uri: "https://auth.example.com/.well-known/jwks.json"
  issuer: "https://auth.example.com"
  audience: "argus-mcp"
  algorithms: ["RS256", "ES256"]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `"anonymous"` | Auth type: `anonymous`, `local`, `jwt`, `oidc` |
| `token` | string | `null` | Static bearer token (for `local` type). Supports `${ENV_VAR}` |
| `jwks_uri` | string | `null` | JWKS URI for JWT key retrieval |
| `issuer` | string | `null` | Expected JWT issuer claim. For OIDC: the issuer's base URL |
| `audience` | string | `null` | Expected JWT audience claim |
| `algorithms` | list[string] | `["RS256", "ES256"]` | Allowed JWT signing algorithms |

**Auth Types:**

| Type | Description |
|------|-------------|
| `anonymous` | No authentication — all clients accepted |
| `local` | Static bearer token (constant-time comparison) |
| `jwt` | JWT validation via JWKS (RS256/ES256) |
| `oidc` | Auto-discovers JWKS from issuer's `/.well-known/openid-configuration` |

See [Authentication](security/authentication.md) for details.

---

## `authorization`

RBAC (Role-Based Access Control) policy enforcement.

```yaml
authorization:
  enabled: true
  default_effect: deny
  policies:
    - effect: allow
      roles: ["admin"]
      resources: ["*"]
    - effect: allow
      roles: ["reader"]
      resources: ["tool:search_*", "resource:docs/*"]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable RBAC policy enforcement |
| `default_effect` | string | `"deny"` | Effect when no policy matches: `"allow"` or `"deny"` |
| `policies` | list[object] | `[]` | Policy rules (see below) |

**Policy Rule:**

| Field | Type | Description |
|-------|------|-------------|
| `effect` | string | `"allow"` or `"deny"` |
| `roles` | list[string] | Roles this policy applies to (from JWT claims) |
| `resources` | list[string] | Resource patterns: `"tool:<name>"`, `"resource:<uri>"`, `"prompt:<name>"`, `"server:<name>"`, `"group:<name>"`, `"*"` |
| `description` | string | Optional human-readable description |

See [Authorization](security/authorization.md) for details.

---

## `registries`

External registry endpoints for server discovery. Each entry defines a
registry that the Argus can query for available MCP servers.

```yaml
registries:
  - name: "official"
    url: "https://registry.mcp.example.com"
    priority: 100
    auth: "api-key"
    api_key_env: "MCP_REGISTRY_KEY"
  - name: "internal"
    url: "https://internal-registry.corp.local"
    priority: 200
    auth: "bearer"
    token_env: "INTERNAL_REGISTRY_TOKEN"
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | **yes** | — | Unique display name for this registry |
| `url` | string | **yes** | — | Registry endpoint URL (must start with `http://` or `https://`) |
| `priority` | integer | no | `100` | Resolution priority (lower = checked first) |
| `auth` | string | no | `"none"` | Authentication type: `"none"`, `"api-key"`, or `"bearer"` |
| `api_key_env` | string | no | — | Environment variable holding the API key (when `auth: "api-key"`) |
| `token_env` | string | no | — | Environment variable holding the bearer token (when `auth: "bearer"`) |

---

## `client`

TUI client configuration. These settings control how the TUI connects to
the Argus server and its display preferences.

```yaml
client:
  server_url: "http://127.0.0.1:9000"
  token: "${ARGUS_CLIENT_TOKEN}"
  theme: "textual-dark"
  poll_interval: 2.0
  servers_config: "~/.config/argus-mcp/servers.json"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server_url` | string | `"http://127.0.0.1:9000"` | URL of the Argus server to connect to |
| `token` | string | — | Authentication token (optional, supports `${ENV_VAR}`) |
| `theme` | string | `"textual-dark"` | Textual theme name for the TUI |
| `poll_interval` | float | `2.0` | Polling interval in seconds (range: 0.5–60.0) |
| `servers_config` | string | — | Path to `servers.json` for multi-server mode |

---

## `feature_flags`

Boolean feature toggles.

```yaml
feature_flags:
  hot_reload: true
  optimizer: false
```

Recognized flags (from `config/flags.py` defaults):

| Flag | Default | Description |
|------|---------|-------------|
| `optimizer` | `false` | Enable the tool optimizer (find_tool / call_tool meta-tools) |
| `hot_reload` | `true` | Enable config hot-reload via management API |
| `outgoing_auth` | `true` | Enable outgoing authentication for backends |
| `session_management` | `true` | Enable session management |
| `yaml_config` | `true` | Enable YAML config file support |
| `container_isolation` | `true` | Enable automatic container isolation for stdio backends |
| `build_on_startup` | `true` | Build container images on server startup |

Unknown flag names are accepted for future-proofing and default to `false`.
Config file watching is always active when a config path is provided — it is
not controlled by a feature flag.

---

## Full Example

See [example_config.yaml](../example_config.yaml) for a comprehensive,
annotated configuration file covering all sections and options.
