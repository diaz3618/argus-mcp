# Architecture Overview

Argus MCP sits between MCP clients (LLMs, IDEs, agents) and multiple backend
MCP servers. It aggregates capabilities, enforces security policies, and provides
operational visibility — all through a single connection point.

## System Diagram

```
                     ┌──────────────────────────────────────────┐
                     │              Argus MCP                   │
                     │                                          │
  MCP Clients        │  ┌─────────┐   ┌───────────────────┐     │
  ─────────────────► │  │Transport│──►│  Middleware Chain │     │
  (Claude, Cursor,   │  │ Layer   │   │                   │     │      Backend MCP Servers
   VS Code, etc.)    │  │         │   │  Auth             │     │
                     │  │ SSE     │   │  AuthZ            │     │      ┌───────────────────┐
  ◄───────────────── │  │         │   │  Telemetry        │     │  ┌──►│ stdio (container) │
  Aggregated tools,  │  │ Stream- │   │  Audit            │     │  │   └───────────────────┘
  resources, prompts │  │ able    │   │  Recovery         │     │  │   ┌─────────────┐
                     │  │ HTTP    │   │  Routing ─────────┼─────┼──┼──►│ SSE server  │
                     │  └─────────┘   └───────────────────┘     │  │   └─────────────┘
                     │                                          │  │   ┌─────────────┐
                     │  ┌──────────────┐  ┌──────────────────┐  │  └──►│ HTTP server │
                     │  │ Management   │  │ Bridge           │  │      └─────────────┘
                     │  │ API          │  │                  │  │
                     │  │ /manage/v1/  │  │ Registry         │  │
                     │  │              │  │ ClientManager    │  │
                     │  │ Health       │  │ StartupCoord     │  │
                     │  │ Status       │  │ Optimizer        │  │
                     │  │ Backends     │  │ ConflictResolver │  │
                     │  │ Events       │  │ Filters          │  │
                     │  │ Hot-reload   │  │ GroupManager     │  │
                     │  └──────────────┘  │ ContainerWrapper │  │
                     │                    └──────────────────┘  │
                     │                                          │
                     │  ┌──────────┐ ┌────────┐  ┌───────────┐  │
                     │  │ Secrets  │ │ Audit  │  │ Telemetry │  │
                     │  │ Store    │ │ Logger │  │ OTel      │  │
                     │  └──────────┘ └────────┘  └───────────┘  │
                     └──────────────────────────────────────────┘
                                         ▲
                                         │ HTTP polling
                                   ┌─────┴─────┐
                                   │    TUI    │
                                   │ (Textual) │
                                   └───────────┘
```

## Package Structure

```
argus_mcp/
├── __init__.py
├── __main__.py          # python -m argus_mcp
├── cli.py               # Entry point: server, build, stop, status, tui, secret, clean
├── constants.py         # Shared constants
├── errors.py            # Base exception hierarchy
├── _error_utils.py      # Error formatting helpers
├── _task_utils.py       # Asyncio task utilities
├── sessions.py          # Named detached-session registry (stop/status)
│
├── config/              # Configuration system
│   ├── loader.py        # JSON/YAML loading, validation
│   ├── schema.py        # Top-level ArgusConfig Pydantic model
│   ├── schema_backends.py  # Backend config models (stdio, SSE, streamable-http)
│   ├── schema_client.py    # Client/TUI config models
│   ├── schema_registry.py  # Registry config models
│   ├── schema_security.py  # Auth, authz, secrets config models
│   ├── schema_server.py    # Server & management config models
│   ├── migration.py     # Legacy → v1 auto-migration
│   ├── diff.py          # Config change detection
│   ├── flags.py         # FeatureFlags
│   ├── watcher.py       # File watcher for hot-reload
│   └── client_gen.py    # Client config generation
│
├── server/              # ASGI server & MCP protocol
│   ├── app.py           # Starlette app + route setup
│   ├── lifespan.py      # Startup/shutdown lifecycle
│   ├── handlers.py      # MCP protocol handlers
│   ├── transport.py     # SSE + Streamable HTTP transports
│   ├── origin.py        # Origin validation middleware (MCP spec)
│   ├── state.py         # Server state management
│   ├── auth/            # Incoming authentication (JWT, OIDC, local)
│   ├── authz/           # RBAC authorization (engine + policies)
│   ├── session/         # Client session tracking (manager + models)
│   └── management/      # REST management API (router, schemas, auth)
│
├── bridge/              # Backend connectivity layer
│   ├── client_manager.py       # Backend connections lifecycle
│   ├── capability_registry.py  # Capability aggregation
│   ├── backend_connection.py   # Backend connection helpers
│   ├── startup_coordinator.py  # Startup orchestration & ordering
│   ├── auth_discovery.py       # Non-blocking OAuth/OIDC auth discovery
│   ├── transport_factory.py    # Transport creation factory
│   ├── subprocess_utils.py     # Subprocess management utilities
│   ├── conflict.py      # Conflict resolution
│   ├── filter.py        # Capability filtering
│   ├── rename.py        # Tool renaming
│   ├── groups.py        # Logical server groups
│   ├── elicitation.py   # MCP elicitation support
│   ├── version_checker.py  # Version drift detection
│   ├── auth/            # Outgoing authentication
│   │   ├── discovery.py     # OAuth/OIDC metadata discovery (RFC 9728)
│   │   ├── pkce.py          # PKCE browser-based auth flow
│   │   ├── provider.py      # Auth provider factory
│   │   ├── store.py         # Token/credential storage
│   │   └── token_cache.py   # Token caching and refresh
│   ├── container/       # Container isolation for stdio backends
│   │   ├── wrapper.py       # Main entry point — wrap_backend()
│   │   ├── image_builder.py # Docker image build orchestration
│   │   ├── runtime.py       # Container runtime detection (Docker/Podman)
│   │   ├── network.py       # Network mode resolution
│   │   └── templates/       # Jinja2 Dockerfile templates
│   │       ├── models.py        # TemplateData, RuntimeConfig, UID constants
│   │       ├── engine.py        # Template rendering engine
│   │       ├── _generators.py   # Per-transport build logic
│   │       ├── validation.py    # Template output validation
│   │       ├── uvx.dockerfile.j2  # Python/uvx backend Dockerfile
│   │       ├── npx.dockerfile.j2  # Node.js/npx backend Dockerfile
│   │       └── go.dockerfile.j2   # Go binary backend Dockerfile
│   ├── health/          # Health checking (checker + circuit breaker)
│   ├── middleware/       # Request middleware chain
│   └── optimizer/       # Tool optimizer (meta-tools + search index)
│
├── runtime/             # Service lifecycle
│   ├── service.py       # ArgusService orchestration
│   └── models.py        # Runtime status models
│
├── audit/               # Audit logging
│   ├── models.py        # AuditEvent (NIST SP 800-53)
│   └── logger.py        # JSONL writer with rotation
│
├── secrets/             # Secret management
│   ├── store.py         # SecretStore facade
│   ├── providers.py     # Env, File, Keyring providers
│   └── resolver.py      # Config secret:name resolution
├── skills/              # Skill packs
│   ├── manifest.py      # SkillManifest model
│   └── manager.py       # Install, enable, discover
│
├── workflows/           # Composite workflows
│   ├── dsl.py           # Workflow step definitions
│   ├── executor.py      # Step execution engine
│   └── composite_tool.py # Workflow-as-tool wrapper
│
├── telemetry/           # OpenTelemetry integration
│   ├── config.py        # Telemetry configuration
│   ├── metrics.py       # Counters, histograms
│   └── tracing.py       # Span management
│
├── registry/            # Server registry
│   ├── client.py        # Registry client
│   ├── cache.py         # Registry cache
│   └── models.py        # Registry data models
│
├── display/             # Console output (headless mode)
│   ├── installer.py     # Backend startup progress display (Rich Live)
│   ├── console.py       # General status display
│   └── logging_config.py # File logging + secret redaction
│
└── tui/                 # Terminal UI (Textual)
    ├── app.py           # ArgusApp
    ├── api_client.py    # HTTP client for management API
    ├── server_manager.py # Multi-server connections
    ├── events.py        # Custom Textual messages
    ├── settings.py      # TUI preferences
    ├── argus.tcss    # Stylesheet
    ├── screens/         # Dashboard, Tools, Registry, Settings, ...
    └── widgets/         # Reusable UI components
```

## Data Flow

### 1. Startup

```
CLI (main)
  → Uvicorn
    → Starlette app_lifespan
      → Load & validate config (JSON/YAML)
      → Resolve secrets (secret:name → values)
      → Create ArgusService
        → StartupCoordinator: sort backends (remotes first, then stdio)
          → Phase 1: launch_remote_tasks()
            → Concurrent (semaphore-gated, stagger 0.5s)
            → For each SSE/HTTP backend:
              → Auth discovery (RFC 9728): non-blocking, PKCE 630s timeout
              → Connect transport
          → Phase 2: build_and_connect_stdio()
            → For each stdio backend:
              → Container wrapper: detect runtime, build image, pre-create container
              → Wrap params: command becomes "docker start -ai <container_id>"
          → Phase 3: gather_remote_results()
            → Await remote tasks, collect pass/fail
        → CapabilityRegistry: discover & aggregate capabilities
        → Apply conflict resolution, filters, renames
        → Build middleware chain
        → Start AuditLogger, SessionManager, HealthChecker
      → Attach to MCP server instance
      → Start management API
```

### 2. MCP Request

```
Client request (list_tools / call_tool / read_resource / get_prompt)
  → Transport layer (SSE or Streamable HTTP)
    → MCP protocol handler
      → Middleware chain:
        1. AuthMiddleware      — validate bearer token, extract identity
        2. AuthzMiddleware     — check RBAC policies
        3. TelemetryMiddleware — create OTel span, record metrics
        4. AuditMiddleware     — log structured audit event
        5. RecoveryMiddleware  — catch exceptions, return clean errors
        6. RoutingMiddleware   — resolve backend, forward request
      → Backend MCP session
    → Response back through chain
  → Client receives result
```

### 3. Management API Request

```
HTTP request → /manage/v1/{endpoint}
  → BearerAuthMiddleware (token check, /health exempt)
    → Route handler
      → Read from ArgusService state
    → JSON response
```

### 4. TUI Polling

```
ArgusApp (Textual)
  → ApiClient polls /manage/v1/ endpoints every 2s
    → Health, Backends, Capabilities, Events
  → Updates widgets with fresh data
  → Handles connection loss/restore gracefully
```

## Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Single connection point** | Clients connect once; Argus routes to N backends |
| **Protocol-native** | Speaks MCP natively — no protocol translation |
| **Transport-agnostic** | Supports stdio, SSE, and Streamable HTTP backends |
| **Container-first isolation** | stdio backends run in hardened containers by default |
| **Middleware pipeline** | Pluggable chain for cross-cutting concerns |
| **Config-driven** | All behavior controlled via YAML config |
| **Defense in depth** | Auth → AuthZ → Audit → Recovery → Container isolation |
| **Graceful degradation** | Backend failures don't crash the gateway |
| **Operational visibility** | Management API + TUI + audit logs + health checks |
