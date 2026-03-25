# Argus MCP

[![Docker Hub Pulls](https://img.shields.io/docker/pulls/diaz3618/argus-mcp?logo=docker&label=Docker%20Hub%20pulls)](https://hub.docker.com/r/diaz3618/argus-mcp)
[![GHCR Pulls](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fghcr-badge.elias.eu.org%2Fapi%2Fdiaz3618%2Fargus-mcp&query=%24.downloadCount&label=GHCR%20pulls&logo=github)](https://ghcr.io/diaz3618/argus-mcp)

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for more details.

## Project Overview

Argus MCP is a **central gateway and management platform** for MCP (Model Context Protocol) servers. It connects to and aggregates capabilities from multiple backend MCP servers (stdio, SSE, or streamable-HTTP) and exposes them to upstream MCP clients through **SSE** (`/sse`) and **Streamable HTTP** (`/mcp`) transports.

The project has a **server/client architecture**:

- **`argus-mcp server`** — Headless server that runs the MCP bridge, management API, and transports.
- **`argus-mcp build`** — Pre-build container images for stdio backends.
- **`argus-mcp tui`** — Textual-based terminal UI that connects to a running server over HTTP.
- **`argus-mcp secret`** — Manage encrypted secrets (set, get, list, delete).
- **`argus-mcp clean`** — Remove containers and images created by Argus MCP.

### Companion Packages

| Package | Entry Point | Description |
|---------|-------------|-------------|
| `argus-cli` | `argus` | Client CLI with 20 command groups and an interactive REPL for managing a running server |
| `argus-cli` | `argus-tui` | Alternative TUI launcher from the client package |
| `argusd` | `argusd` | Go sidecar daemon for Docker container and Kubernetes pod management (Unix Domain Socket API) |

See the [CLI Reference](docs/cli/) and [REPL Guide](docs/cli/repl.md) for details.

**Core Advantages:**

1. **Simplified Client Configuration:** MCP clients connect to one Argus MCP address to access all backend services.
2. **Capability Aggregation:** Aggregates MCP tools, resources, and prompts from multiple sources into a single endpoint.
3. **Management API:** RESTful API at `/manage/v1/` for runtime inspection and control of backend services.
4. **Multi-Server TUI:** Connect the TUI to multiple Argus MCP servers simultaneously and switch between them.
5. **Security:** JWT/OIDC authentication, RBAC authorization, encrypted secret storage, and log redaction.

## Installation and Setup

Requires Python 3.10+.

### From PyPI

**`uv tool install`** — fastest, isolated environment, auto-managed (recommended):

```bash
uv tool install argus-mcp
```

**`pipx`** — same isolation concept, more established:

```bash
pipx install argus-mcp
```

**`pip`** — installs into the current environment:

```bash
pip install argus-mcp
```

> **Quick try:** Run without installing using `uv run argus-mcp --help`

After installing, verify with:

```bash
argus-mcp --help
```

### From Docker

See the [Docker usage guide](docs/docker.md).

```bash
docker run --rm diaz3618/argus-mcp:latest --help
```

### From Source

1. **Clone Repository**

    ```bash
    git clone https://github.com/diaz3618/argus-mcp.git
    cd argus-mcp
    ```

2. **Create and Activate Virtual Environment**

    ```bash
    uv venv
    source .venv/bin/activate   # Linux/macOS
    # .venv\Scripts\activate    # Windows
    ```

3. **Install Dependencies**

    ```bash
    uv sync
    ```

## Quick Start

### View Help

```bash
argus-mcp --help
```

```text
usage: argus-mcp [-h] {server,build,stop,status,tui,secret,clean} ...

Argus MCP v0.8.0

positional arguments:
  {server,build,stop,status,tui,secret,clean}
    server       Run the headless Argus server (Uvicorn + MCP bridge,
                 with container isolation)
    build        Pre-build container images for all stdio backends
    stop         Stop a detached Argus server
    status       List all running Argus server sessions
    tui          Launch the Textual TUI connected to a running Argus server
    secret       Manage encrypted secrets (set, get, list, delete)
    clean        Remove containers and images created by argus-mcp

options:
  -h, --help     show this help message and exit
```

### Start the Server

```bash
# Default: listen on 127.0.0.1:9000, auto-detect config file
argus-mcp server

# Custom host, port, and log level
argus-mcp server --host 0.0.0.0 --port 8080 --log-level debug

# Explicit config file
argus-mcp server --config /path/to/config.yaml
```

Config file resolution order: `--config` flag → `ARGUS_CONFIG` env var → auto-detect (`config.yaml` → `config.yml`).

The server exposes:

- **SSE endpoint** at `http://<host>:<port>/sse` — for MCP clients using the SSE transport.
- **Streamable HTTP endpoint** at `http://<host>:<port>/mcp` — for MCP clients using the newer Streamable HTTP transport.
- **Management API** at `http://<host>:<port>/manage/v1/` — for the TUI and automation.

Set the `ARGUS_MGMT_TOKEN` environment variable to enable bearer token authentication on the management API.

### Launch the TUI

```bash
# Connect to a local server
argus-mcp tui --server http://127.0.0.1:9000

# With authentication
argus-mcp tui --server http://127.0.0.1:9000 --token YOUR_TOKEN

# Multi-server mode (uses ~/.config/argus-mcp/servers.json)
argus-mcp tui --servers-config /path/to/servers.json
```

### Multi-Server Configuration

Create a `servers.json` file to manage multiple Argus MCP servers:

```json
{
  "servers": [
    {
      "name": "local",
      "url": "http://127.0.0.1:9000"
    },
    {
      "name": "production",
      "url": "https://argus.example.com:9000",
      "token": "your-production-token"
    }
  ],
  "active": "local"
}
```

Default location: `~/.config/argus-mcp/servers.json`

### MCP Client Connection

After starting the server, connect any MCP-compatible client to one of the transport endpoints:

| Transport | URL |
|-----------|-----|
| SSE | `http://<host>:<port>/sse` |
| Streamable HTTP | `http://<host>:<port>/mcp` |

Supported clients include Claude Desktop, Cursor, Cline, and any other MCP-compatible application.

### Logs

Runtime logs are saved in the `logs/` directory with timestamped filenames.

## Configuration

The configuration file defines both server settings and backend MCP server connections.

### Config Format (YAML)

The config uses a versioned YAML format with server settings and backend definitions:

```yaml
version: "1"

server:
  host: "0.0.0.0"
  port: 9000
  transport: sse                # "sse" or "streamable-http"
  management:
    enabled: true
    token: "${ARGUS_MGMT_TOKEN}"

backends:
  my_stdio_server:
    type: stdio
    command: python
    args: ["path/to/server.py"]
    env:
      API_KEY: "${MY_API_KEY}"

  remote_sse:
    type: sse
    url: "https://mcp.example.com/sse"

  remote_streamable:
    type: streamable-http
    url: "https://mcp.example.com/mcp"
```

### Backend Types

**stdio** — Local MCP server processes managed by Argus MCP.

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | `"stdio"` |
| `command` | Yes | Executable to run |
| `args` | No | Command arguments (default: `[]`) |
| `env` | No | Environment variables |
| `container` | No | Container isolation config (enabled by default for stdio) |

**sse** — Connect to MCP servers over SSE; optionally start a local process.

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | `"sse"` |
| `url` | Yes | SSE endpoint URL |
| `command` | No | Optional local process to start |
| `args` | No | Command arguments |
| `headers` | No | Extra HTTP headers |
| `auth` | No | Outgoing auth config (`static`, `oauth2`, or `pkce`) |

**streamable-http** — Connect to MCP servers using Streamable HTTP transport.

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | `"streamable-http"` |
| `url` | Yes | Streamable HTTP endpoint URL |
| `headers` | No | Extra HTTP headers |
| `auth` | No | Outgoing auth config (`static`, `oauth2`, or `pkce`) |

> Streamable HTTP backends must always set `type: streamable-http` explicitly.

### Common Backend Options

All backend types also support:

| Field | Default | Description |
|-------|---------|-------------|
| `group` | `"default"` | Logical server group name |
| `filters` | — | Per-capability allow/deny lists (tools, resources, prompts) |
| `tool_overrides` | — | Rename or override descriptions for individual tools |
| `timeouts` | — | Per-backend timeout overrides (`init`, `cap_fetch`, `sse_startup`) |

### Environment Variable Expansion

All string values support `${VAR_NAME}` syntax for environment variable expansion.

### Secret References

String values can use `secret:name` syntax to resolve values from encrypted storage (see `argus-mcp secret`).

## Management API

The management API is mounted at `/manage/v1/` and provides:

| Endpoint | Method | Description |
| -------- | ------ | ----------- |
| `/manage/v1/health` | GET | Health check (uptime, backend health summary) |
| `/manage/v1/status` | GET | Server status (version, config, endpoints, feature flags) |
| `/manage/v1/backends` | GET | List all backends with connection state and capabilities |
| `/manage/v1/groups` | GET | List logical server groups |
| `/manage/v1/capabilities` | GET | Aggregated tools, resources, prompts |
| `/manage/v1/sessions` | GET | Active MCP client sessions |
| `/manage/v1/events` | GET | Recent event log entries |
| `/manage/v1/events/stream` | GET | Live SSE event stream |
| `/manage/v1/reload` | POST | Hot-reload configuration |
| `/manage/v1/reconnect/{name}` | POST | Reconnect a specific backend |
| `/manage/v1/shutdown` | POST | Graceful server shutdown |

When `ARGUS_MGMT_TOKEN` is set, include `Authorization: Bearer <token>` in requests.
