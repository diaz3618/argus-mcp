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
| [CLI Reference](cli/) | Command-line interface |
| [Architecture](architecture/) | System design, component overview, data flow |
| [Management API](api/) | REST endpoints for monitoring and control |
| [Security](security/) | Authentication, authorization, secrets |
| [TUI Guide](tui/) | Interactive terminal UI |
| [Middleware](middleware.md) | Request pipeline and middleware chain |
| [Audit & Observability](audit/) | Audit logging, telemetry, health checks |
| [Skills](skills/) | Portable bundles of tools, workflows, and config |
| [Workflows](workflows/) | Composite tool pipelines (DAG-based) |
| [Registry](registry/) | Browse and install MCP servers from remote catalogs |
| [Optimizer](optimizer/) | `find_tool` / `call_tool` meta-tools |
| [Config Sync](sync/) | Hot-reload and change detection |

## Documentation Map

```
docs/
├── README.md              ← You are here
├── getting-started.md     ← Install & first run
├── configuration.md       ← Full config reference
├── middleware.md           ← Middleware pipeline
│
├── architecture/
│   ├── 00-overview.md     ← High-level architecture
│   ├── 01-server.md       ← Server & transport layer
│   ├── 02-bridge.md       ← Bridge: routing, registry, forwarding
│   ├── 03-config.md       ← Config loading pipeline
│   └── 04-runtime.md      ← Service lifecycle
│
├── cli/
│   ├── README.md          ← CLI overview
│   ├── server.md          ← `argus-mcp server`
│   ├── tui.md             ← `argus-mcp tui`
│   └── secret.md          ← `argus-mcp secret`
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
| **Management API** | REST interface at `/manage/v1/` for monitoring and control |
| **TUI** | Textual-based terminal UI that connects to the management API |
| **Optimizer** | Replaces full tool catalog with `find_tool` + `call_tool` meta-tools |
| **Skill** | A portable bundle of tools, workflows, and config |
| **Workflow** | A composite tool pipeline expressed as a DAG of steps |
| **Registry** | Remote catalog of MCP servers you can browse and install |
| **Config Sync** | Watches config files for changes and hot-reloads without restarts |

## Version

Current version: **0.7.0**

License: GPL-3.0-only
