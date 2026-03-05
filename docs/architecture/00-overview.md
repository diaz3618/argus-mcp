# Architecture Overview

Argus MCP sits between MCP clients (LLMs, IDEs, agents) and multiple backend
MCP servers. It aggregates capabilities, enforces security policies, and provides
operational visibility — all through a single connection point.

## System Diagram

```
                     ┌──────────────────────────────────────────┐
                     │              Argus MCP                │
                     │                                          │
  MCP Clients        │  ┌─────────┐   ┌───────────────────┐     │
  ─────────────────► │  │Transport│──►│  Middleware Chain │     │
  (Claude, Cursor,   │  │ Layer   │   │                   │     │      Backend MCP Servers
   VS Code, etc.)    │  │         │   │  Auth             │     │
                     │  │ SSE     │   │  AuthZ            │     │      ┌──────────────┐
  ◄───────────────── │  │         │   │  Telemetry        │     │  ┌──►│ stdio server │
  Aggregated tools,  │  │ Stream- │   │  Audit            │     │  │   └──────────────┘
  resources, prompts │  │ able    │   │  Recovery         │     │  │   ┌──────────────┐
                     │  │ HTTP    │   │  Routing ─────────┼─────┼──┼──►│ SSE server   │
                     │  └─────────┘   └───────────────────┘     │  │   └──────────────┘
                     │                                          │  │   ┌──────────────┐
                     │  ┌──────────────┐  ┌──────────────────┐  │  └──►│ HTTP server  │
                     │  │ Management   │  │ Bridge           │  │      └──────────────┘
                     │  │ API          │  │                  │  │
                     │  │ /manage/v1/  │  │ Registry         │  │
                     │  │              │  │ ClientManager    │  │
                     │  │ Health       │  │ Forwarder        │  │
                     │  │ Status       │  │ Optimizer        │  │
                     │  │ Backends     │  │ ConflictResolver │  │
                     │  │ Events       │  │ Filters          │  │
                     │  │ Hot-reload   │  │ GroupManager     │  │
                     │  └──────────────┘  └──────────────────┘  │
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
├── cli.py               # Entry point: server, tui, secret subcommands
├── constants.py         # Shared constants
├── errors.py            # Base exception hierarchy
├── sessions.py          # Named detached-session registry (stop/status)
│
├── config/              # Configuration system
│   ├── loader.py        # JSON/YAML loading, validation
│   ├── schema.py        # Pydantic config models
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
│   ├── auth/            # Incoming authentication
│   ├── authz/           # RBAC authorization
│   ├── session/         # Client session tracking
│   └── management/      # REST management API
│
├── bridge/              # Backend connectivity layer
│   ├── client_manager.py    # Backend connections
│   ├── capability_registry.py  # Capability aggregation
│   ├── forwarder.py     # Request forwarding
│   ├── conflict.py      # Conflict resolution
│   ├── filter.py        # Capability filtering
│   ├── rename.py        # Tool renaming
│   ├── groups.py        # Logical server groups
│   ├── elicitation.py   # MCP elicitation support
│   ├── version_checker.py  # Version drift detection
│   ├── auth/            # Outgoing authentication
│   ├── health/          # Health checking
│   ├── middleware/       # Request middleware chain
│   └── optimizer/       # Tool optimizer (meta-tools)
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
│
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
│   ├── metrics.py       # Counters, histograms
│   └── tracing.py       # Span management
│
├── registry/            # Server registry
│   └── client.py        # Registry client
│
├── display/             # Console output (headless mode)
│   ├── console.py       # Status display
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
        → ClientManager: connect to all backends
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
| **Middleware pipeline** | Pluggable chain for cross-cutting concerns |
| **Config-driven** | All behavior controlled via YAML config |
| **Defense in depth** | Auth → AuthZ → Audit → Recovery layers |
| **Graceful degradation** | Backend failures don't crash the gateway |
| **Operational visibility** | Management API + TUI + audit logs + health checks |
