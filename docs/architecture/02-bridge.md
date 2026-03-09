# Bridge: Routing, Registry & Orchestration

The bridge layer connects Argus to backend MCP servers, discovers their
capabilities, orchestrates startup, and routes incoming requests to the
correct backend.

## ClientManager

`argus_mcp/bridge/client_manager.py` manages the lifecycle of backend
connections.

**Responsibilities:**

- Start/stop backend MCP sessions (stdio, SSE, streamable-http)
- Track connection state per backend (6-phase lifecycle)
- Provide access to active sessions for request forwarding
- Support reconnection of individual backends

**Backend Lifecycle Phases:**

```
Pending → Initializing → Ready → Degraded → Failed
                           │                    │
                           └── ShuttingDown ◄───┘
```

| Phase | Description |
|-------|-------------|
| `Pending` | Configured but not yet started |
| `Initializing` | Connection in progress |
| `Ready` | Connected and serving capabilities |
| `Degraded` | Connected but health check failing |
| `Failed` | Connection lost or startup error |
| `ShuttingDown` | Graceful disconnect in progress |

## CapabilityRegistry

`argus_mcp/bridge/capability_registry.py` aggregates capabilities from all
connected backends.

**Process:**

1. Each backend exposes tools, resources, and prompts
2. Registry fetches capability lists from each backend session
3. Applies **filters** (allow/deny glob patterns)
4. Applies **conflict resolution** (first-wins, prefix, priority, error)
5. Applies **tool renames** (tool_overrides)
6. Builds a route map: `capability_name → backend_name`

**Route Map Example:**

```python
{
    "search_web": "browser-server",
    "read_file": "filesystem-server",
    "browser_navigate": "browser-server",  # prefix strategy
}
```

## Conflict Resolution

`argus_mcp/bridge/conflict.py` handles duplicate capability names across
backends.

| Strategy | Behavior |
|----------|----------|
| `first-wins` | First backend to register a name keeps it |
| `prefix` | Prefix with backend name: `backend_toolname` |
| `priority` | Use configured `order` list to pick the winner |
| `error` | Raise `CapabilityConflictError` at startup |

## Capability Filtering

`argus_mcp/bridge/filter.py` applies per-backend glob pattern filters:

```yaml
filters:
  tools:
    allow: ["search_*", "read_*"]
    deny: ["dangerous_*"]
```

- If `allow` is non-empty, only matching names pass
- If `deny` is non-empty, matching names are excluded
- Deny takes precedence over allow

## Tool Renaming

`argus_mcp/bridge/rename.py` applies per-backend tool overrides:

```yaml
tool_overrides:
  original_name:
    name: better_name
    description: "Improved description"
```

The original name is preserved in the route map for forwarding.

## Server Groups

`argus_mcp/bridge/groups.py` — `GroupManager` organizes backends into logical
groups:

```yaml
backends:
  server-a:
    type: stdio
    command: ...
    group: search-tools
  server-b:
    type: sse
    url: ...
    group: search-tools
```

Groups are queryable via `GET /manage/v1/groups?group=search-tools`.

## Startup Coordinator

`argus_mcp/bridge/startup_coordinator.py` orchestrates backend initialization
using a 3-phase strategy that starts remote backends before local ones:

**Type Priority:**

| Priority | Type | Rationale |
|----------|------|-----------|
| 0 | `streamable-http` | Network connections are I/O-bound, benefit from early start |
| 1 | `sse` | Same as above |
| 2 | `stdio` | Local processes require CPU; may trigger container builds |

**3-Phase Startup:**

1. **Launch remote tasks** — All `streamable-http` and `sse` backends are
   started concurrently (up to `STARTUP_CONCURRENCY` at a time) with a
   `STARTUP_STAGGER_DELAY` between each launch.
2. **Build and connect stdio** — Stdio backends are processed sequentially.
   Each may trigger container image builds, so serial execution avoids
   resource contention.
3. **Gather remote results** — Wait for all remote tasks started in phase 1
   to complete, collecting results and errors.

This ordering ensures network-bound connections have maximum time to
handshake while stdio backends build images.

## Auth Discovery

`argus_mcp/bridge/auth_discovery.py` handles non-blocking OAuth/OIDC
metadata discovery for backends that use outgoing authentication.

- Runs via `asyncio.create_task()` — does not block server startup
- Uses a `AUTH_DISCOVERY_TIMEOUT` of 630 seconds for slow providers
- Deduplicates discovery requests per provider URL
- Populates the outgoing auth provider after discovery completes

## Transport Factory

`argus_mcp/bridge/transport_factory.py` encapsulates the creation of MCP
transport connections for each backend type (stdio, SSE, streamable-http).
It is called by `ClientManager` when establishing new backend connections.

## Backend Connection Helpers

`argus_mcp/bridge/backend_connection.py` provides shared connection utilities
used by `ClientManager` during backend initialization and reconnection.

## Request Routing

Request forwarding uses the middleware chain's `RoutingMiddleware` which:

1. Looks up the capability in the route map
2. Resolves to the backend name
3. Gets the backend's MCP session from ClientManager
4. Calls the appropriate MCP method on the session
5. Returns the result

## Health Checking

`argus_mcp/bridge/health/` monitors backend health:

- Periodic health probes to each backend
- Maps health results to backend lifecycle phases
- Degrades gracefully — unhealthy backends are marked but not removed
- Health status visible via management API and TUI

## Container Isolation

`argus_mcp/bridge/container/` provides automatic container isolation for
stdio backends. Every stdio backend runs inside a hardened container by
default — no manual configuration required.

### Architecture

```
wrap_backend() ← called by ClientManager for each stdio backend
  │
  ├── RuntimeFactory.detect()  → Docker or Podman
  ├── is_already_containerised()  → pass through if command=docker
  ├── classify_command()  → "uvx", "npx", "go", or None
  ├── ensure_image()  → build or reuse cached Docker image
  │     ├── TemplateData + RuntimeConfig  → typed template context
  │     ├── render_template()  → Jinja2 Dockerfile generation
  │     └── docker build  → image tagged argus-<backend>:latest
  ├── _create_container()  → docker create (pre-creation)
  └── return wrapped StdioServerParameters
        command="docker", args=["start", "-ai", <container_id>]
```

### Image Building Pipeline

The template engine renders per-transport Jinja2 Dockerfile templates:

| Transport | Template | Base Image |
|-----------|----------|------------|
| `uvx` (Python) | `uvx.dockerfile.j2` | `python:3.13-slim` |
| `npx` (Node.js) | `npx.dockerfile.j2` | `node:22-alpine` |
| `go` (Go binary) | `go.dockerfile.j2` | `golang:1.24-alpine` |

Templates are parameterized with `TemplateData` — a typed dataclass that
provides package name, binary path, builder image, system dependencies, and
container user identity fields. No raw `**kwargs` or untyped dicts.

### Container User Identity

All Argus-built images use the industry-standard non-root identity:

| Field | Value | Source |
|-------|-------|--------|
| UID | `65532` | distroless/Chainguard "nonroot" standard |
| Username | `nonroot` | Created in each Dockerfile template |
| Home | `/home/nonroot` | Dedicated writable home directory |

These are defined as constants in `templates/models.py` — the **single source
of truth** consumed by both templates and the runtime wrapper.

### Security Hardening

Every container runs with these security defaults:

| Control | Setting |
|---------|---------|
| Filesystem | `--read-only` root FS |
| Capabilities | `--cap-drop ALL` |
| Privilege escalation | `--security-opt no-new-privileges` |
| SELinux | `--security-opt label=disable` (for stdio I/O compatibility) |
| Process management | `--init` (proper signal propagation) |
| Memory limit | `--memory 512m` (configurable) |
| CPU limit | `--cpus 1` (configurable) |
| Writable tmpfs | `/tmp` and `/home/nonroot` with `mode=1777` (sticky bit) |
| Network | `--network bridge` for built images (configurable) |
| Environment | `HOME` and `TMPDIR` injected before user env vars |

### Two-Step Container Lifecycle

Argus uses `docker create` + `docker start -ai` instead of `docker run`
to avoid stdio attach hangs observed on certain Docker + storage-driver +
SELinux combinations:

1. **Pre-create** — `docker create --rm -i <flags> <image>` → returns container ID
2. **Attach** — MCP SDK launches `docker start -ai <container_id>` as subprocess

This decouples image pulling/layer setup from the stdio attach, producing
reliable stdin/stdout streams.

### Graceful Fallback

Container isolation degrades gracefully at every step:

- No runtime (Docker/Podman) → bare subprocess + warning
- Runtime unhealthy → bare subprocess
- Unknown command type → bare subprocess
- Image build fails → bare subprocess
- Container create fails → bare subprocess
- Per-backend `container_isolation: false` → bare subprocess
- `ARGUS_CONTAINER_ISOLATION=false` → all backends run bare

### Pre-Building Images

The `argus-mcp build` CLI command pre-builds all container images and
pre-creates containers, avoiding cold-start delays at server launch:

```bash
argus-mcp build --config config.yaml
```

### Cleanup

`cleanup_all_containers()` is called during server shutdown to remove
all tracked pre-created containers. Individual backends can be cleaned
up via `cleanup_container(svr_name)`.

### Container Module Structure

| Module | Purpose |
|--------|---------|
| `wrapper.py` | Main entry point — `wrap_backend()`, `cleanup_all_containers()` |
| `image_builder.py` | Image build orchestration, command classification |
| `runtime.py` | Container runtime detection (Docker, Podman) via `RuntimeFactory` |
| `network.py` | Network mode resolution (`bridge`, `none`, custom) |
| `templates/models.py` | `TemplateData`, `RuntimeConfig`, UID/user/home constants |
| `templates/engine.py` | Jinja2 template rendering with identity defaults |
| `templates/_generators.py` | Per-transport image build logic |
| `templates/validation.py` | Rendered Dockerfile validation |
| `templates/*.j2` | Jinja2 Dockerfile templates (uvx, npx, go) |

## Tool Optimizer

`argus_mcp/bridge/optimizer/` implements the `ToolIndex`:

When large numbers of tools overwhelm LLM context windows, the optimizer
replaces the full catalog with two meta-tools:

- **`find_tool`** — Search tools by natural language query
- **`call_tool`** — Invoke a found tool by name

The `ToolIndex` maintains an in-memory index of all tools with TF-IDF-style
scoring for search relevance.

## Elicitation

`argus_mcp/bridge/elicitation.py` supports the MCP elicitation protocol,
allowing backends to request additional input from users during tool execution.

## Version Checking

`argus_mcp/bridge/version_checker.py` detects version drift between
connected backends and a tool registry, alerting when tool versions fall behind.
