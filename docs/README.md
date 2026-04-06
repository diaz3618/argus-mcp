# Argus MCP Documentation

> **Argus MCP** is a central gateway and management platform for
> [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) servers.
> It aggregates capabilities from multiple backends, provides a REST management
> API, an interactive TUI, and enterprise-grade security features.

## Quick Navigation

| Section | Description |
|---------|-------------|
| [Getting Started](getting-started.md) | Installation, first run, quick config |
| [Configuration](configuration.md) | Full config reference (YAML) |
| [CLI Reference](cli/) | `argus-mcp` server commands and `argus` client commands |
| [REPL Guide](cli/repl.md) | Interactive `argus` read-eval-print loop |
| [Architecture](architecture/) | System design, component overview, data flow |
| [argusd Daemon](architecture/07-argusd.md) | Go sidecar for Docker and Kubernetes management |
| [Management API](api/) | REST endpoints for monitoring and control |
| [Security](security/) | Authentication, authorization, secrets |
| [TUI Guide](tui/) | Interactive terminal UI (containers, Kubernetes, catalog) |
| [Middleware](middleware.md) | Request pipeline and middleware chain |
| [Audit & Observability](audit/) | Audit logging, telemetry, health checks |
| [Skills](skills/) | Portable bundles of tools, workflows, and config |
| [Workflows](workflows/) | Composite tool pipelines (DAG-based) |
| [Registry](registry/) | Browse and install MCP servers from remote catalogs |
| [Plugins](architecture/05-plugins.md) | Built-in and external plugin system |
| [Optimizer](optimizer/) | `find_tool` / `call_tool` meta-tools |
| [Config Sync](sync/) | Hot-reload and change detection |
| [Docker](docker.md) | Docker build and deployment |
| [Kubernetes](kubernetes.md) | Helm chart deployment |

## Documentation Map

```
docs/
├── README.md              ← You are here
├── getting-started.md     ← Install & first run
├── configuration.md       ← Full config reference
├── middleware.md           ← Middleware pipeline
├── docker.md              ← Docker build & deployment
├── kubernetes.md           ← Helm chart deployment
│
├── architecture/
│   ├── 00-overview.md     ← High-level architecture
│   ├── 01-server.md       ← Server & transport layer
│   ├── 02-bridge.md       ← Bridge: routing, registry, orchestration
│   ├── 03-config.md       ← Config loading pipeline
│   ├── 04-runtime.md      ← Service lifecycle
│   ├── 05-plugins.md      ← Plugin system (built-in & external)
│   ├── 06-connection-pool.md ← Session pool, HTTP pool, retry
│   └── 07-argusd.md       ← argusd Go daemon (Docker & Kubernetes)
│
├── cli/
│   ├── README.md          ← CLI overview (argus-mcp + argus)
│   ├── repl.md            ← argus interactive REPL
│   ├── server.md          ← `argus-mcp server`
│   ├── tui.md             ← `argus-mcp tui`
│   └── secret.md          ← `argus-mcp secret`
│
│   Remaining subcommands (build, stop, status, clean): see
│   `argus-mcp <command> --help` or the CLI overview.
│
├── security/
│   ├── README.md          ← Security overview
│   ├── authentication.md  ← Incoming auth (JWT, OIDC, local)
│   ├── authorization.md   ← RBAC policies
│   ├── secrets.md         ← Encrypted secret management
│   └── outgoing-auth.md   ← Backend auth (OAuth2, static)
│
├── api/
│   ├── README.md          ← API overview & auth
│   └── endpoints.md       ← Endpoint reference
│
├── tui/
│   ├── README.md          ← TUI overview & keybindings
│   └── screens.md         ← Screen reference
│
├── audit/
│   └── README.md          ← Audit logging, OTel, health monitoring
│
├── skills/
│   └── README.md          ← Skill packs — bundled tools & workflows
│
├── workflows/
│   └── README.md          ← Composite workflow pipelines
│
├── registry/
│   └── README.md          ← MCP server registry & catalogs
│
├── optimizer/
│   └── README.md          ← find_tool / call_tool meta-tools
│
└── sync/
    └── README.md          ← Config hot-reload & change detection
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Backend** | An MCP server that Argus connects to (stdio, SSE, or streamable-http) |
| **Capability** | A tool, resource, or prompt exposed by a backend |
| **Bridge** | Internal layer that connects to backends and aggregates capabilities |
| **Middleware** | Pluggable request pipeline (auth → authz → telemetry → audit → recovery → routing) |
| **Container Isolation** | Automatic per-backend hardened containers for stdio backends (Docker/Podman) |
| **Management API** | REST interface at `/manage/v1/` for monitoring and control |
| **argus CLI** | Client CLI (`argus`) for interacting with a running server — supports one-shot commands and an interactive REPL |
| **REPL** | Read-eval-print loop in the `argus` CLI with tab completion, aliases, backend scoping, and watch mode |
| **argusd** | Go sidecar daemon providing Docker container and Kubernetes pod management over a Unix Domain Socket |
| **TUI** | Textual-based terminal UI that connects to the management API |
| **Containers Screen** | TUI screen for managing Docker containers via argusd |
| **Kubernetes Screen** | TUI screen for managing Kubernetes pods via argusd |
| **Optimizer** | Replaces full tool catalog with `find_tool` + `call_tool` meta-tools |
| **Skill** | A portable bundle of tools, workflows, and config |
| **Workflow** | A composite tool pipeline expressed as a DAG of steps |
| **Registry** | Remote catalog of MCP servers you can browse and install |
| **Config Sync** | Watches config files for changes and hot-reloads without restarts |

## Version

Current version: **0.8.1**

License: GPL-3.0-only
